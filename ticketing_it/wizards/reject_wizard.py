# -*- coding: utf-8 -*-

from odoo import models, fields


class ITTicketRejectWizard(models.TransientModel):
    _name = 'it.ticket.reject.wizard'
    _description = 'Reject Ticket Wizard'

    ticket_id = fields.Many2one('it.ticket', 'Ticket', required=True)
    rejection_reason = fields.Text('Rejection Reason', required=True)

    def action_reject(self):
        # FIX: use sudo() so the wizard can call do_reject() even when the
        # calling user (e.g. line manager) only has limited ACL rights on
        # it.ticket.  Security is enforced inside do_reject() via
        # _check_reject_access(), so sudo() here does not bypass any checks.
        self.ticket_id.sudo().do_reject(self.rejection_reason)
        return {'type': 'ir.actions.act_window_close'}