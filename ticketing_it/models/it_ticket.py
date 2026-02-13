# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ITTicket(models.Model):
    _name = 'it.ticket'
    _description = 'IT Support Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'create_date desc'

    # ======================
    # BASIC FIELDS
    # ======================

    name = fields.Char(
        string='Ticket Number',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        tracking=True
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        default=lambda self: self._get_current_employee(),
        tracking=True
    )

    partner_id = fields.Many2one(
        'res.partner',
        related='employee_id.user_id.partner_id',
        store=True,
        readonly=True
    )

    department_id = fields.Many2one(
        'hr.department',
        related='employee_id.department_id',
        store=True,
        readonly=True
    )

    # ======================
    # DETAILS
    # ======================

    ticket_type = fields.Selection([
        ('hardware', 'Hardware Issue'),
        ('software', 'Software Issue'),
        ('social_media', 'Social Media Access'),
        ('network', 'Network Issue'),
        ('other', 'Other'),
    ], required=True, tracking=True)

    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], default='1', required=True, tracking=True)

    subject = fields.Char(required=True, tracking=True)
    description = fields.Html(required=True)
    required_date = fields.Date()

    # ======================
    # STATE
    # ======================

    state = fields.Selection([
        ('draft', 'Draft'),
        ('manager_approval', 'Pending Line Manager'),
        ('it_approval', 'Pending IT Manager'),
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('rejected', 'Rejected'),
    ], default='draft', tracking=True)

    # ======================
    # APPROVERS
    # ======================

    line_manager_id = fields.Many2one(
        'res.users',
        compute='_compute_line_manager',
        store=True
    )

    it_manager_id = fields.Many2one(
        'res.users',
        compute='_compute_it_manager',
        store=True
    )

    assigned_to_id = fields.Many2one('res.users')

    # ======================
    # DATES
    # ======================

    submitted_date = fields.Datetime(readonly=True)
    manager_approval_date = fields.Datetime(readonly=True)
    it_approval_date = fields.Datetime(readonly=True)
    done_date = fields.Datetime(readonly=True)

    # ======================
    # REJECTION
    # ======================

    rejection_reason = fields.Text(readonly=True)
    rejected_by_id = fields.Many2one('res.users', readonly=True)
    rejected_date = fields.Datetime(readonly=True)

    # =========================================================
    # DEFAULT EMPLOYEE
    # =========================================================

    def _get_current_employee(self):
        return self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)],
            limit=1
        )

    # =========================================================
    # COMPUTE METHODS
    # =========================================================

    @api.depends('employee_id')
    def _compute_line_manager(self):
        for rec in self:
            if rec.employee_id and rec.employee_id.parent_id:
                rec.line_manager_id = rec.employee_id.parent_id.user_id
            else:
                rec.line_manager_id = False

    @api.depends('department_id')
    def _compute_it_manager(self):
        for rec in self:
            rec.it_manager_id = False

    # =========================================================
    # WORKFLOW ACTION METHODS  (IMPORTANT FIX)
    # =========================================================

    def action_submit(self):
        for rec in self:
            rec.state = 'manager_approval'
            rec.submitted_date = fields.Datetime.now()

    def action_manager_approve(self):
        for rec in self:
            rec.state = 'it_approval'
            rec.manager_approval_date = fields.Datetime.now()

    def action_it_approve(self):
        for rec in self:
            rec.state = 'assigned'
            rec.it_approval_date = fields.Datetime.now()

    def action_start_work(self):
        for rec in self:
            rec.state = 'in_progress'

    def action_done(self):
        for rec in self:
            rec.state = 'done'
            rec.done_date = fields.Datetime.now()

    def action_reject(self):
        for rec in self:
            rec.state = 'rejected'
            rec.rejected_by_id = self.env.user
            rec.rejected_date = fields.Datetime.now()
