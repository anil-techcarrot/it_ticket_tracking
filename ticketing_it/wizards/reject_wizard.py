# -*- coding: utf-8 -*-

from odoo import models, fields


class ITTicketRejectWizard(models.TransientModel):
    _name = 'it.ticket.reject.wizard'
    _description = 'Reject Ticket Wizard'

    ticket_id = fields.Many2one('it.ticket', 'Ticket', required=True)
    rejection_reason = fields.Text('Rejection Reason', required=True)

    def action_reject(self):
        self.ticket_id.do_reject(self.rejection_reason)
        return {'type': 'ir.actions.act_window_close'}