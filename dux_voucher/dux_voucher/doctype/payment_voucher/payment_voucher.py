import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from dux_voucher.dux_voucher.api.utils import (
    _detect_party_type,
    _get_party_account,
    _get_account_currency,
    _validate_bank_cash_account,
    _submit_doc,
    _safe_cancel,
    get_mop_type,
)


class PaymentVoucher(Document):

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def insert(self, *args, **kwargs):
        """Wipe inherited ``backend_references`` rows on amendment
        *before* Frappe runs its cancelled-link validation.

        Frappe's amend flow copies the cancelled doc whole — including
        the ``backend_references`` child table whose rows point at the
        now-cancelled Payment Entry / JE. ``Document.insert`` then runs
        ``_validate_links()`` ahead of ``before_insert``, so a
        ``before_insert`` cleanup is too late: it has already thrown
        ``Cannot link cancelled document``.

        Overriding ``insert()`` lets us scrub the rows in the narrow
        window between the doc being instantiated and the lifecycle
        starting. The fresh submission will rebuild
        ``backend_references`` from the PE / JE it posts, so the
        inherited rows are pure garbage and there is nothing worth
        preserving.
        """
        if self.amended_from:
            self.set("backend_references", [])
        return super().insert(*args, **kwargs)

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------
    def validate(self):
        self._validate_basics()
        if self.entry_mode == "Party-wise":
            self._validate_party_wise()
        elif self.entry_mode == "Head-wise":
            self._validate_head_wise()
        elif self.entry_mode == "Contra Entry":
            self._validate_contra()
        elif self.entry_mode == "Party + Head Entry":
            self._validate_combined()

    def _validate_basics(self):
        if not self.company:
            frappe.throw(_("Company is required"))
        if not self.posting_date:
            frappe.throw(_("Posting Date is required"))

    def _validate_party_wise(self):
        if not self.mode_of_payment:
            frappe.throw(_("Payment Method is required"))
        if not self.paid_from_account:
            frappe.throw(_("Paid From Account is required"))
        if not self.party_rows:
            frappe.throw(_("Please add at least one party row"))

        _validate_bank_cash_account(self.paid_from_account, "Paid From Account")

        row_total = sum(flt(r.amount) for r in self.party_rows)
        if not flt(self.amount):
            self.amount = row_total
        elif abs(flt(self.amount) - row_total) > 0.005:
            frappe.throw(
                _("Amount ({0}) must equal sum of party rows ({1})").format(
                    flt(self.amount), row_total
                )
            )

        for row in self.party_rows:
            if not row.party:
                frappe.throw(_("Row {0}: Party is required").format(row.idx))
            if not flt(row.amount) or flt(row.amount) <= 0:
                frappe.throw(
                    _("Row {0}: Amount must be greater than zero").format(row.idx)
                )
            if not row.party_type:
                row.party_type = _detect_party_type(row.party)
                if not row.party_type:
                    frappe.throw(
                        _("Row {0}: '{1}' not found as Customer, "
                          "Supplier or Employee").format(row.idx, row.party)
                    )
            if not frappe.db.exists(row.party_type, row.party):
                frappe.throw(
                    _("Row {0}: {1} '{2}' does not exist").format(
                        row.idx, row.party_type, row.party
                    )
                )

    def _validate_head_wise(self):
        if not self.mode_of_payment:
            frappe.throw(_("Payment Method is required"))
        if not self.paid_from_account:
            frappe.throw(_("Paid From Account is required"))
        if not self.account_rows:
            frappe.throw(_("Please add at least one account row"))

        _validate_bank_cash_account(self.paid_from_account, "Paid From Account")

        for row in self.account_rows:
            if not row.account:
                frappe.throw(_("Row {0}: Account is required").format(row.idx))
            if flt(row.debit) < 0 or flt(row.credit) < 0:
                frappe.throw(
                    _("Row {0}: Debit and Credit cannot be negative").format(row.idx)
                )
            if flt(row.debit) > 0 and flt(row.credit) > 0:
                frappe.throw(
                    _("Row {0}: A row cannot have both Debit and Credit").format(row.idx)
                )

        total_debit = sum(flt(r.debit) for r in self.account_rows)
        total_credit = sum(flt(r.credit) for r in self.account_rows)
        net_amount = total_debit - total_credit

        if net_amount <= 0:
            frappe.throw(
                _("Total Debit ({0}) must be greater than Total Credit ({1}). "
                  "The difference will be auto-credited to '{2}'").format(
                    total_debit, total_credit, self.paid_from_account
                )
            )

        self.amount = net_amount

    def _validate_contra(self):
        if not self.transfer_from_account:
            frappe.throw(_("Transfer From Account is required"))
        if not self.transfer_to_account:
            frappe.throw(_("Transfer To Account is required"))
        if self.transfer_from_account == self.transfer_to_account:
            frappe.throw(
                _("Transfer From and Transfer To accounts cannot be the same")
            )
        if not flt(self.amount) or flt(self.amount) <= 0:
            frappe.throw(_("Amount must be greater than zero"))

        _validate_bank_cash_account(self.transfer_from_account, "Transfer From Account")
        _validate_bank_cash_account(self.transfer_to_account, "Transfer To Account")

    # ------------------------------------------------------------------
    # On Submit
    # ------------------------------------------------------------------
    def on_submit(self):
        refs = []
        try:
            if self.entry_mode == "Party-wise":
                refs = self._create_party_payment_entries()
            elif self.entry_mode == "Head-wise":
                refs = self._create_head_wise_journal_entry()
            elif self.entry_mode == "Contra Entry":
                refs = self._create_contra_payment_entry()
            elif self.entry_mode == "Party + Head Entry":
                refs = self._create_combined_journal_entry()
        except frappe.ValidationError:
            raise
        except Exception as e:
            frappe.db.rollback()
            frappe.throw(
                _("Error creating backend entries: {0}").format(str(e))
            )

        for ref in refs:
            row = frappe.new_doc("PV Backend Reference")
            row.parent = self.name
            row.parenttype = "Payment Voucher"
            row.parentfield = "backend_references"
            row.backend_doctype = ref["doctype"]
            row.backend_document = ref["name"]
            row.party = ref.get("party", "")
            row.amount = ref.get("amount", 0)
            row.insert(ignore_permissions=True)

        frappe.db.set_value("Payment Voucher", self.name, "is_posted", 1)

    # ------------------------------------------------------------------
    # On Cancel
    # ------------------------------------------------------------------
    def on_cancel(self):
        refs = frappe.get_all(
            "PV Backend Reference",
            filters={"parent": self.name},
            fields=["backend_doctype", "backend_document"]
        )
        for ref in refs:
            _safe_cancel(ref.backend_doctype, ref.backend_document)

        frappe.db.set_value("Payment Voucher", self.name, "is_posted", 0)

    # ------------------------------------------------------------------
    # Party-wise — one Payment Entry per row
    # ------------------------------------------------------------------
    def _create_party_payment_entries(self):
        refs = []
        for row in self.party_rows:
            party_account = _get_party_account(
                row.party_type, row.party, self.company
            )
            if not party_account:
                frappe.throw(
                    _("Could not find ledger account for {0} '{1}'. "
                      "Please set default payable/receivable account "
                      "in Company or Party master.").format(
                        row.party_type, row.party
                    )
                )

            pe = frappe.new_doc("Payment Entry")
            pe.payment_type = "Pay"
            pe.company = self.company
            pe.posting_date = self.posting_date
            pe.mode_of_payment = self.mode_of_payment
            pe.party_type = row.party_type
            pe.party = row.party
            pe.paid_from = self.paid_from_account
            pe.paid_to = party_account
            pe.paid_from_account_currency = _get_account_currency(
                self.paid_from_account, self.company
            )
            pe.paid_to_account_currency = _get_account_currency(
                party_account, self.company
            )
            pe.paid_amount = flt(row.amount)
            pe.received_amount = flt(row.amount)
            pe.source_exchange_rate = 1
            pe.target_exchange_rate = 1
            pe.reference_no = self.reference_no or ""
            pe.reference_date = self.reference_date or self.posting_date
            pe.custom_remarks = 1
            pe.remarks = self.remarks or ""
            pe.custom_source_voucher_doctype = "Payment Voucher"
            pe.custom_source_voucher = self.name
            # Project is an accounting dimension: ERPNext's get_gl_dict seeds
            # every GL row with the parent's `project`, so setting it here is
            # all that's needed for the payment to be attributable.
            #
            # PER ROW, not per voucher. One voucher routinely pays several
            # parties and only some of them belong to the project — a real
            # example paid five, of which two were project work. Tagging every
            # Payment Entry from the header would overstate the project by the
            # unrelated rows. Same row-then-header idiom as the JE modes.
            pe.project = row.project or self.project or ""

            _submit_doc(pe)
            refs.append({
                "doctype": "Payment Entry",
                "name": pe.name,
                "party": row.party,
                "amount": flt(row.amount)
            })
        return refs

    # ------------------------------------------------------------------
    # Head-wise — one Journal Entry with auto bank/cash credit row
    # ------------------------------------------------------------------
    def _create_head_wise_journal_entry(self):
        mop_type = get_mop_type(self.mode_of_payment)
        voucher_type = "Cash Entry" if mop_type == "Cash" else "Bank Entry"

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = voucher_type
        je.company = self.company
        je.posting_date = self.posting_date
        je.cheque_no = self.reference_no or ""
        je.cheque_date = self.reference_date or None
        je.user_remark = self.remarks or ""
        je.custom_source_voucher_doctype = "Payment Voucher"
        je.custom_source_voucher = self.name

        for row in self.account_rows:
            je.append("accounts", {
                "account": row.account,
                "debit_in_account_currency": flt(row.debit),
                "credit_in_account_currency": flt(row.credit),
                "cost_center": row.cost_center or self.cost_center or "",
                "project": row.project or self.project or "",
            })

        # Auto-add bank/cash credit row
        total_debit = sum(flt(r.debit) for r in self.account_rows)
        total_credit = sum(flt(r.credit) for r in self.account_rows)
        net_credit = total_debit - total_credit

        je.append("accounts", {
            "account": self.paid_from_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": net_credit,
            "cost_center": self.cost_center or "",
            "project": self.project or "",
        })

        _submit_doc(je)
        return [{
            "doctype": "Journal Entry",
            "name": je.name,
            "amount": net_credit
        }]

    # ------------------------------------------------------------------
    # Contra — Payment Entry Internal Transfer
    # ------------------------------------------------------------------
    def _create_contra_payment_entry(self):
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Internal Transfer"
        pe.company = self.company
        pe.posting_date = self.posting_date
        pe.mode_of_payment = self.mode_of_payment or ""
        pe.paid_from = self.transfer_from_account
        pe.paid_to = self.transfer_to_account
        pe.paid_from_account_currency = _get_account_currency(
            self.transfer_from_account, self.company
        )
        pe.paid_to_account_currency = _get_account_currency(
            self.transfer_to_account, self.company
        )
        pe.paid_amount = flt(self.amount)
        pe.received_amount = flt(self.amount)
        pe.source_exchange_rate = 1
        pe.target_exchange_rate = 1
        pe.reference_no = self.reference_no or ""
        pe.reference_date = self.reference_date or self.posting_date
        pe.custom_remarks = 1
        pe.remarks = self.remarks or ""
        pe.custom_source_voucher_doctype = "Payment Voucher"
        pe.custom_source_voucher = self.name
        # A contra moves money between two of our own bank/cash accounts, so
        # the header project is the only sensible source — there are no rows.
        pe.project = self.project or ""

        _submit_doc(pe)
        return [{
            "doctype": "Payment Entry",
            "name": pe.name,
            "amount": flt(self.amount)
        }]

    # ------------------------------------------------------------------
    # Party + Head Entry -- validation
    # ------------------------------------------------------------------
    def _validate_combined(self):
        if not self.mode_of_payment:
            frappe.throw(_("Payment Method is required"))
        if not self.paid_from_account:
            frappe.throw(_("Paid From Account is required"))
        if not self.combined_rows:
            frappe.throw(_("Please add at least one row"))

        _validate_bank_cash_account(self.paid_from_account, "Paid From Account")

        for row in self.combined_rows:
            if not row.account:
                frappe.throw(_("Row {0}: Account is required").format(row.idx))
            if flt(row.debit) < 0 or flt(row.credit) < 0:
                frappe.throw(
                    _("Row {0}: Debit and Credit cannot be negative").format(row.idx)
                )
            if flt(row.debit) > 0 and flt(row.credit) > 0:
                frappe.throw(
                    _("Row {0}: A row cannot have both Debit and Credit").format(row.idx)
                )
            # If party is set, validate it exists
            if row.party:
                if not row.party_type:
                    row.party_type = _detect_party_type(row.party)
                    if not row.party_type:
                        frappe.throw(
                            _("Row {0}: '{1}' not found as Customer, "
                              "Supplier or Employee").format(row.idx, row.party)
                        )
                if not frappe.db.exists(row.party_type, row.party):
                    frappe.throw(
                        _("Row {0}: {1} '{2}' does not exist").format(
                            row.idx, row.party_type, row.party
                        )
                    )

        total_debit = sum(flt(r.debit) for r in self.combined_rows)
        total_credit = sum(flt(r.credit) for r in self.combined_rows)
        net_amount = total_debit - total_credit

        if net_amount <= 0:
            frappe.throw(
                _("Total Debit ({0}) must be greater than Total Credit ({1}). "
                  "The difference will be auto-credited to '{2}'").format(
                    total_debit, total_credit, self.paid_from_account
                )
            )

        self.amount = net_amount

    # ------------------------------------------------------------------
    # Party + Head Entry -- one Journal Entry with party mapping
    # ------------------------------------------------------------------
    def _create_combined_journal_entry(self):
        mop_type = get_mop_type(self.mode_of_payment)
        voucher_type = "Cash Entry" if mop_type == "Cash" else "Bank Entry"

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = voucher_type
        je.company = self.company
        je.posting_date = self.posting_date
        je.cheque_no = self.reference_no or ""
        je.cheque_date = self.reference_date or None
        je.user_remark = self.remarks or ""
        je.custom_source_voucher_doctype = "Payment Voucher"
        je.custom_source_voucher = self.name

        for row in self.combined_rows:
            je.append("accounts", {
                "account": row.account,
                "party_type": row.party_type or "",
                "party": row.party or "",
                "debit_in_account_currency": flt(row.debit),
                "credit_in_account_currency": flt(row.credit),
                "cost_center": row.cost_center or self.cost_center or "",
                "project": row.project or self.project or "",
            })

        # Auto-add bank/cash credit row
        total_debit = sum(flt(r.debit) for r in self.combined_rows)
        total_credit = sum(flt(r.credit) for r in self.combined_rows)
        net_credit = total_debit - total_credit

        je.append("accounts", {
            "account": self.paid_from_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": net_credit,
            "cost_center": self.cost_center or "",
            "project": self.project or "",
        })

        _submit_doc(je)
        return [{
            "doctype": "Journal Entry",
            "name": je.name,
            "amount": net_credit
        }]
