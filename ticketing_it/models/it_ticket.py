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
            if it_manager_group:
                ticket.it_manager_id = it_manager_group.users[0] if it_manager_group.users else False
            else:
                ticket.it_manager_id = False

    # CRUD Override
    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('it.ticket') or 'New'
        ticket = super(ITTicket, self).create(vals)

        # Auto-submit for portal users
        if self.env.user.has_group('base.group_portal'):
            ticket.action_submit()
        return ticket

    # Workflow Actions
    def action_submit(self):
        for ticket in self:
            if not ticket.line_manager_id:
                raise UserError(_("No line manager found for %s") % ticket.employee_id.name)

            ticket.write({
                'state': 'manager_approval',
                'submitted_date': fields.Datetime.now()
            })

            # Activity for manager
            ticket.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=ticket.line_manager_id.id,
                summary=_('Ticket Approval Required: %s') % ticket.name,
                note=_('Please approve IT ticket from %s') % ticket.employee_id.name
            )

            # Email notification
            template = self.env.ref('it_ticketing.email_template_manager_approval',
                                    raise_if_not_found=False)
            if template:
                template.send_mail(ticket.id, force_send=True)

            # Post message
            ticket.message_post(
                body=_("Ticket submitted to Line Manager: %s") % ticket.line_manager_id.name,
                message_type='notification'
            )

    def action_manager_approve(self):
        for ticket in self:
            if self.env.user != ticket.line_manager_id:
                raise UserError(_("Only line manager can approve"))

            ticket.write({
                'state': 'it_approval',
                'manager_approval_date': fields.Datetime.now()
            })

            # Clear activity
            ticket.activity_unlink(['mail.mail_activity_data_todo'])

            # Activity for IT manager
            if ticket.it_manager_id:
                ticket.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=ticket.it_manager_id.id,
                    summary=_('IT Approval Required: %s') % ticket.name,
                    note=_('Ticket approved by line manager')
                )

            # Email notification
            template = self.env.ref('it_ticketing.email_template_it_approval',
                                    raise_if_not_found=False)
            if template:
                template.send_mail(ticket.id, force_send=True)

            ticket.message_post(
                body=_("Approved by Manager. Sent to IT Manager"),
                message_type='notification'
            )

    def action_it_approve(self):
        for ticket in self:
            if not self.env.user.has_group('it_ticketing.group_it_manager'):
                raise UserError(_("Only IT manager can approve"))

            ticket.write({
                'state': 'assigned',
                'it_approval_date': fields.Datetime.now()
            })

            ticket.activity_unlink(['mail.mail_activity_data_todo'])

            # Email to IT team
            template = self.env.ref('it_ticketing.email_template_it_assigned',
                                    raise_if_not_found=False)
            if template:
                template.send_mail(ticket.id, force_send=True)

            ticket.message_post(
                body=_("Approved by IT Manager. Assigned to IT Team"),
                message_type='notification'
            )

    def action_reject(self):
        return {
            'name': _('Reject Ticket'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.ticket.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id}
        }

    def do_reject(self, reason):
        self.write({
            'state': 'rejected',
            'rejection_reason': reason,
            'rejected_by_id': self.env.user.id,
            'rejected_date': fields.Datetime.now()
        })

        self.activity_unlink(['mail.mail_activity_data_todo'])

        template = self.env.ref('it_ticketing.email_template_rejection',
                                raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)

        self.message_post(
            body=_("Rejected by %s<br/>Reason: %s") % (self.env.user.name, reason),
            message_type='notification'
        )

    def action_start_work(self):
        self.write({'state': 'in_progress'})
        self.message_post(body=_("Work started by %s") % self.env.user.name)

    def action_done(self):
        self.write({
            'state': 'done',
            'done_date': fields.Datetime.now()
        })

        template = self.env.ref('it_ticketing.email_template_done',
                                raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)

    # Portal Methods
    def _compute_access_url(self):
        super(ITTicket, self)._compute_access_url()
        for ticket in self:
            ticket.access_url = '/my/tickets/%s' % ticket.id