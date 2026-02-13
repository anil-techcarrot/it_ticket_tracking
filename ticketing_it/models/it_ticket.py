# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ITTicket(models.Model):
    _name = 'it.ticket'
    _description = 'IT Support Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'create_date desc'

    # Basic Fields
    name = fields.Char('Ticket Number', required=True, copy=False,
                       readonly=True, default='New', tracking=True)
    employee_id = fields.Many2one('hr.employee', 'Employee', required=True,
                                  default=lambda self: self._get_current_employee(),
                                  tracking=True)
    partner_id = fields.Many2one('res.partner', 'Contact',
                                 related='employee_id.user_id.partner_id',
                                 store=True, readonly=True)
    department_id = fields.Many2one('hr.department', 'Department',
                                    related='employee_id.department_id',
                                    store=True, readonly=True)

    # Ticket Details
    ticket_type = fields.Selection([
        ('hardware', 'Hardware Issue'),
        ('software', 'Software Issue'),
        ('social_media', 'Social Media Access'),
        ('network', 'Network Issue'),
        ('other', 'Other'),
    ], string='Ticket Type', required=True, tracking=True)

    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], string='Priority', default='1', required=True, tracking=True)

    subject = fields.Char('Subject', required=True, tracking=True)
    description = fields.Html('Description', required=True)
    required_date = fields.Date('Required By Date')

    # Workflow State
    state = fields.Selection([
        ('draft', 'Draft'),
        ('manager_approval', 'Pending Line Manager'),
        ('it_approval', 'Pending IT Manager'),
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Approvers
    line_manager_id = fields.Many2one('res.users', 'Line Manager',
                                      compute='_compute_line_manager',
                                      store=True, readonly=True)
    it_manager_id = fields.Many2one('res.users', 'IT Manager',
                                    compute='_compute_it_manager',
                                    store=True, readonly=True)
    assigned_to_id = fields.Many2one('res.users', 'Assigned To')

    # Timestamps
    submitted_date = fields.Datetime('Submitted Date', readonly=True, tracking=True)
    manager_approval_date = fields.Datetime('Manager Approval Date', readonly=True, tracking=True)
    it_approval_date = fields.Datetime('IT Approval Date', readonly=True, tracking=True)
    done_date = fields.Datetime('Done Date', readonly=True, tracking=True)

    # Rejection
    rejection_reason = fields.Text('Rejection Reason', readonly=True, tracking=True)
    rejected_by_id = fields.Many2one('res.users', 'Rejected By', readonly=True)
    rejected_date = fields.Datetime('Rejected Date', readonly=True)

    # Computed Methods
    def _get_current_employee(self):
        return self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)

    @api.depends('employee_id')
    def _compute_line_manager(self):
        for ticket in self:
            if ticket.employee_id and ticket.employee_id.parent_id:
                ticket.line_manager_id = ticket.employee_id.parent_id.user_id
            else:
                ticket.line_manager_id = False

    @api.depends('department_id')
    def _compute_it_manager(self):
        for ticket in self:
            it_manager_group = self.env.ref('ticketing_it.group_it_manager', raise_if_not_found=False)