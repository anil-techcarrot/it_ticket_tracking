# -*- coding: utf-8 -*-

from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    ticket_count = fields.Integer('Tickets', compute='_compute_ticket_count')

    def _compute_ticket_count(self):
        for employee in self:
            employee.ticket_count = self.env['it.ticket'].search_count([
                ('employee_id', '=', employee.id)
            ])

    def action_view_tickets(self):
        return {
            'name': 'IT Tickets',
            'type': 'ir.actions.act_window',
            'res_model': 'it.ticket',
            'view_mode': 'tree,form',
            'domain': [('employee_id', '=', self.id)],
        }