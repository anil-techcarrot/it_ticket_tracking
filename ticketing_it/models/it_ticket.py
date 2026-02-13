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
        """Get IT manager from group"""
        for rec in self:
            it_manager_group = self.env.ref('ticketing_it.group_it_manager', raise_if_not_found=False)
            if it_manager_group and it_manager_group.users:
                rec.it_manager_id = it_manager_group.users[0]
            else:
                rec.it_manager_id = False

    # =========================================================
    # WORKFLOW ACTION METHODS (WITH EMAIL SENDING)
    # =========================================================

    @api.model
    def create(self, vals):
        """Auto-generate ticket number"""
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('it.ticket') or 'New'

        record = super(ITTicket, self).create(vals)

        # Auto-submit for portal users
        if self.env.user.has_group('base.group_portal'):
            record.action_submit()

        return record

    def action_submit(self):
        """Submit ticket and send email to line manager"""
        for rec in self:
            if not rec.line_manager_id:
                raise UserError(_("No line manager found for employee: %s") % rec.employee_id.name)

            rec.state = 'manager_approval'
            rec.submitted_date = fields.Datetime.now()

            # Send email to line manager
            template = self.env.ref('ticketing_it.email_template_manager_approval', raise_if_not_found=False)
            if template:
                template.send_mail(rec.id, force_send=True)

            # Create activity for line manager
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=rec.line_manager_id.id,
                summary=_('Ticket Approval Required: %s') % rec.name,
                note=_('Please review and approve IT ticket from %s') % rec.employee_id.name
            )

            # Post message in chatter
            rec.message_post(
                body=_("Ticket submitted to Line Manager: %s") % rec.line_manager_id.name,
                message_type='notification'
            )

    def action_manager_approve(self):
        """Manager approves and sends to IT Manager"""
        for rec in self:
            if self.env.user != rec.line_manager_id:
                raise UserError(_("Only the line manager can approve this ticket"))

            rec.state = 'it_approval'
            rec.manager_approval_date = fields.Datetime.now()

            # Clear line manager activity
            rec.activity_unlink(['mail.mail_activity_data_todo'])

            # Send email to IT manager
            template = self.env.ref('ticketing_it.email_template_it_approval', raise_if_not_found=False)
            if template and rec.it_manager_id:
                template.send_mail(rec.id, force_send=True)

            # Create activity for IT manager
            if rec.it_manager_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=rec.it_manager_id.id,
                    summary=_('IT Approval Required: %s') % rec.name,
                    note=_('Ticket approved by line manager. Please review.')
                )

            # Post message
            rec.message_post(
                body=_("Approved by Line Manager. Sent to IT Manager"),
                message_type='notification'
            )

    def action_it_approve(self):
        """IT Manager approves and assigns to IT team"""
        for rec in self:
            if not self.env.user.has_group('ticketing_it.group_it_manager'):
                raise UserError(_("Only IT managers can approve this ticket"))

            rec.state = 'assigned'
            rec.it_approval_date = fields.Datetime.now()

            # Clear IT manager activity
            rec.activity_unlink(['mail.mail_activity_data_todo'])

            # Send email to IT team
            template = self.env.ref('ticketing_it.email_template_it_assigned', raise_if_not_found=False)
            if template:
                template.send_mail(rec.id, force_send=True)

            # Post message
            rec.message_post(
                body=_("Approved by IT Manager. Assigned to IT Team"),
                message_type='notification'
            )

    def action_start_work(self):
        """IT team starts working"""
        for rec in self:
            rec.state = 'in_progress'
            rec.message_post(
                body=_("Work started by %s") % self.env.user.name,
                message_type='notification'
            )

    def action_done(self):
        """Mark ticket as done and notify employee"""
        for rec in self:
            rec.state = 'done'
            rec.done_date = fields.Datetime.now()

            # Send resolution email to employee
            template = self.env.ref('ticketing_it.email_template_done', raise_if_not_found=False)
            if template:
                template.send_mail(rec.id, force_send=True)

            # Post message
            rec.message_post(
                body=_("Ticket completed and employee notified"),
                message_type='notification'
            )

    def action_reject(self):
        """Open rejection wizard"""
        self.ensure_one()
        return {
            'name': _('Reject Ticket'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.ticket.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id}
        }

    def do_reject(self, reason):
        """Actually perform rejection (called by wizard)"""
        for rec in self:
            rec.state = 'rejected'
            rec.rejection_reason = reason
            rec.rejected_by_id = self.env.user
            rec.rejected_date = fields.Datetime.now()

            # Clear any pending activities
            rec.activity_unlink(['mail.mail_activity_data_todo'])

            # Send rejection email to employee
            template = self.env.ref('ticketing_it.email_template_rejection', raise_if_not_found=False)
            if template:
                template.send_mail(rec.id, force_send=True)

            # Post message
            rec.message_post(
                body=_("Ticket rejected by %s<br/>Reason: %s") % (self.env.user.name, reason),
                message_type='notification'
            )

    # Portal method
    def _compute_access_url(self):
        """Compute portal URL"""
        super(ITTicket, self)._compute_access_url()
        for ticket in self:
            ticket.access_url = '/my/tickets/%s' % ticket.id
