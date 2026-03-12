# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError, AccessError
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)


class ITTicket(models.Model):
    _name = 'it.ticket'
    _description = 'IT Support Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

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
    ], required=True, tracking=True, string='Ticket Type')

    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], default='1', required=True, tracking=True, string='Priority')

    subject = fields.Char(required=True, tracking=True, string='Subject')
    description = fields.Html(required=True, string='Description')
    required_date = fields.Date(string='Required By Date')
    user_id = fields.Many2one('res.users', string="Assigned To")

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
    ], default='draft', tracking=True, string='Status')

    # ======================
    # APPROVERS
    # ======================

    line_manager_id = fields.Many2one(
        'res.users',
        compute='_compute_line_manager',
        store=True,
        string='Line Manager'
    )

    it_manager_id = fields.Many2one(
        'res.users',
        compute='_compute_it_manager',
        store=True,
        string='IT Manager'
    )

    # ===== UPDATED =====
    assigned_to_id = fields.Many2one(
        'res.users',
        string="Assigned To",
        tracking=True
    )

    # ======================
    # DATES
    # ======================

    submitted_date = fields.Datetime(readonly=True, string='Submitted Date')
    manager_approval_date = fields.Datetime(readonly=True, string='Manager Approval Date')
    it_approval_date = fields.Datetime(readonly=True, string='IT Approval Date')
    done_date = fields.Datetime(readonly=True, string='Completion Date')
    month_solved = fields.Char(string="Month", compute='_compute_month_solved', store=True)
    resolution_time = fields.Float(string="Resolution Time (hours)", compute='_compute_resolution_time', store=True)
    last_reminder_sent = fields.Datetime(
        readonly=True,
        string='Last Reminder Sent'
    )

    # ======================
    # REJECTION
    # ======================

    rejection_reason = fields.Text(readonly=True, string='Rejection Reason')
    rejected_by_id = fields.Many2one('res.users', readonly=True, string='Rejected By')
    rejected_date = fields.Datetime(readonly=True, string='Rejection Date')

    # =========================================================
    # HELPER: GET FROM EMAIL DYNAMICALLY FROM ODOO SETTINGS
    # =========================================================
    allowed_it_users = fields.Many2many(
        "res.users", compute="_compute_allowed_it_users"
    )
    show_it_manager = fields.Boolean(
        string="Visible to IT Manager",
        compute="_compute_show_to_it_manager",
        store=True,
    )
    show_it_teams = fields.Boolean(
        string="Visible to IT team",
        compute="_compute_show_to_it_team",
        store=True,
    )
    is_line_manager = fields.Boolean(compute="_compute_user_roles")
    is_it_manager = fields.Boolean(compute="_compute_user_roles")
    show_to_line_manager = fields.Boolean(
        compute="_compute_show_line_manager"
    )

    line_manager_user_id = fields.Many2one('res.users', string='Line Manager User')

    # ======================
    # PROCESSING TIME FIELDS
    # ======================
    manager_processing_time = fields.Float(
        string="Manager Processing Time (hours)",
        compute='_compute_manager_processing_time',
        store=True
    )
    it_processing_time = fields.Float(
        string="IT Manager Processing Time (hours)",
        compute='_compute_it_processing_time',
        store=True
    )
    it_team_processing_time = fields.Float(
        string="IT Team Processing Time (hours)",
        compute='_compute_it_team_processing_time',
        store=True
    )
    total_resolution_time = fields.Float(
        string="Total Resolution Time (hours)",
        compute='_compute_total_resolution_time',
        store=True
    )

    # ======================
    # REPORTING FIELDS (DAYS)
    # ======================

    manager_processing_days = fields.Float(
        string="Manager Processing (Days)",
        compute="_compute_processing_days",
        store=True,
        aggregator="avg"
    )

    it_processing_days = fields.Float(
        string="IT Manager Processing (Days)",
        compute="_compute_processing_days",
        store=True,
        aggregator="avg"
    )

    it_team_processing_days = fields.Float(
        string="IT Team Processing (Days)",
        compute="_compute_processing_days",
        store=True,
        aggregator="avg"
    )

    @api.depends('submitted_date', 'manager_approval_date', 'it_approval_date', 'done_date')
    def _compute_processing_days(self):
        for rec in self:
            if rec.submitted_date and rec.manager_approval_date:
                delta = rec.manager_approval_date - rec.submitted_date
                rec.manager_processing_days = delta.total_seconds() / 86400
            else:
                rec.manager_processing_days = 0

            if rec.manager_approval_date and rec.it_approval_date:
                delta = rec.it_approval_date - rec.manager_approval_date
                rec.it_processing_days = delta.total_seconds() / 86400
            else:
                rec.it_processing_days = 0

            if rec.it_approval_date and rec.done_date:
                delta = rec.done_date - rec.it_approval_date
                rec.it_team_processing_days = delta.total_seconds() / 86400
            else:
                rec.it_team_processing_days = 0

    # ======================
    # COMPUTE METHODS
    # ======================
    @api.depends('submitted_date', 'manager_approval_date')
    def _compute_manager_processing_time(self):
        for rec in self:
            if rec.submitted_date and rec.manager_approval_date:
                delta = rec.manager_approval_date - rec.submitted_date
                rec.manager_processing_time = delta.total_seconds() / 3600
            else:
                rec.manager_processing_time = 0

    @api.depends('manager_approval_date', 'it_approval_date')
    def _compute_it_processing_time(self):
        for rec in self:
            if rec.manager_approval_date and rec.it_approval_date:
                delta = rec.it_approval_date - rec.manager_approval_date
                rec.it_processing_time = delta.total_seconds() / 3600
            else:
                rec.it_processing_time = 0

    @api.depends('it_approval_date', 'done_date', 'state')
    def _compute_it_team_processing_time(self):
        for rec in self:
            if rec.it_approval_date and rec.done_date:
                delta = rec.done_date - rec.it_approval_date
                rec.it_team_processing_time = delta.total_seconds() / 3600
            else:
                rec.it_team_processing_time = 0

    @api.depends('submitted_date', 'done_date')
    def _compute_total_resolution_time(self):
        for rec in self:
            if rec.submitted_date and rec.done_date:
                delta = rec.done_date - rec.submitted_date
                rec.total_resolution_time = delta.total_seconds() / 3600
            else:
                rec.total_resolution_time = 0

    @api.depends('employee_id')
    def _compute_show_line_manager(self):
        for ticket in self:
            if ticket.employee_id and ticket.employee_id.parent_id:
                manager_email = ticket.employee_id.parent_id.work_email
                if manager_email:
                    user = self.env['res.users'].search([('email', '=', manager_email)], limit=1)
                    if user:
                        ticket.line_manager_user_id = user.id
                    else:
                        ticket.line_manager_user_id = False
                else:
                    ticket.line_manager_user_id = False
            else:
                ticket.line_manager_user_id = False

    @api.depends('line_manager_id')
    def _compute_user_roles(self):
        for rec in self:
            rec.is_line_manager = (
                rec.line_manager_id == self.env.user
                if rec.line_manager_id
                else False
            )
            rec.is_it_manager = self.env.user.has_group('ticketing_it.group_it_manager')

    @api.depends('state')
    def _compute_show_to_it_manager(self):
        for ticket in self:
            ticket.show_it_manager = ticket.state not in ['draft', 'manager_approval']

    @api.depends('state')
    def _compute_show_to_it_team(self):
        for ticket in self:
            ticket.show_it_teams = ticket.state in ['assigned', 'done']

    @api.depends()
    def _compute_allowed_it_users(self):
        it_team_group = self.env.ref("ticketing_it.group_it_team")
        for ticket in self:
            ticket.allowed_it_users = it_team_group.user_ids

    def _get_from_email(self):
        ICP = self.env['ir.config_parameter'].sudo()
        default_from = ICP.get_param('mail.default.from')
        catchall_domain = ICP.get_param('mail.catchall.domain')
        if default_from:
            if catchall_domain and '@' not in default_from:
                return '{}@{}'.format(default_from, catchall_domain)
            return default_from
        company_email = self.env.company.email
        if company_email:
            return company_email
        return False

    # =========================================================
    # HELPER: FIND IT MANAGER VIA SQL
    # =========================================================

    def _find_it_manager(self):
        it_manager_group = self.env.ref(
            'ticketing_it.group_it_manager',
            raise_if_not_found=False
        )
        if not it_manager_group:
            _logger.error("IT Manager group 'ticketing_it.group_it_manager' not found.")
            return False

        self.env.cr.execute("""
            SELECT ru.id
            FROM res_users ru
            JOIN res_groups_users_rel rel ON rel.uid = ru.id
            WHERE rel.gid = %s
              AND ru.active = true
              AND ru.share = false
            ORDER BY ru.id
            LIMIT 1
        """, (it_manager_group.id,))

        row = self.env.cr.fetchone()
        if row:
            user = self.env['res.users'].sudo().browse(row[0])
            _logger.info("IT Manager found via SQL: %s | Email: %s", user.name, user.email)
            return user

        _logger.warning("No IT Manager found in group.")
        return False

    # =========================================================
    # EMAIL HELPERS — Odoo 17 hosted fix
    # Bypasses partner_id override bug — sends mail.mail directly
    # =========================================================

    def _send_ticket_email(self, recipient_partner, subject, body):
        """
        Send email directly using mail.mail.
        Bypasses Odoo 17 hosted bug where template.send_mail() always
        sends to ticket.partner_id instead of the intended recipient.
        """
        if not recipient_partner or not recipient_partner.email:
            _logger.warning("No recipient email for ticket %s", self.name)
            return
        mail = self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': body,
            'email_to': recipient_partner.email,
            'recipient_ids': [(4, recipient_partner.id)],
            'model': 'it.ticket',
            'res_id': self.id,
        })
        mail.send()
        _logger.info("Email sent to %s for ticket %s", recipient_partner.email, self.name)

    def _build_ticket_email_body(self, header_color, header_title,
                                  button_color, button_url,
                                  recipient_name, intro_text, rows):
        """
        Build fully rendered HTML email with big VIEW IT SUPPORT TICKET button.
        rows = list of (label, value) tuples.
        All values are pre-rendered Python strings — no Odoo template engine used.
        """
        rows_html = ""
        for i, (label, value) in enumerate(rows):
            bg = ' style="background-color: #f2f2f2;"' if i % 2 == 0 else ''
            rows_html += f"""
            <tr{bg}>
                <td style="padding: 10px; border: 1px solid #ddd; width: 35%;"><strong>{label}</strong></td>
                <td style="padding: 10px; border: 1px solid #ddd;">{value or ''}</td>
            </tr>"""

        return f"""
<div style="font-family: Arial, sans-serif; padding: 20px; max-width: 600px; margin: 0 auto;">
    <div style="background-color: {header_color}; padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
        <h2 style="color: white; margin: 0;">{header_title}</h2>
    </div>
    <div style="background-color: #f0f4f8; padding: 30px; text-align: center;
                border-left: 1px solid #ddd; border-right: 1px solid #ddd;">
        <p style="margin: 0 0 20px 0; font-size: 15px; color: #555;">
            Click below to view and take action on this ticket
        </p>
        <a href="{button_url}"
           style="display: inline-block; background-color: {button_color}; color: white;
                  text-decoration: none; padding: 20px 60px; border-radius: 8px;
                  font-size: 20px; font-weight: bold; letter-spacing: 1px;
                  box-shadow: 0 4px 10px rgba(0,0,0,0.2);">
            &#128065; VIEW IT SUPPORT TICKET
        </a>
    </div>
    <div style="border: 1px solid #ddd; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
        <p>Dear <strong>{recipient_name}</strong>,</p>
        <p>{intro_text}</p>
        <table style="border-collapse: collapse; width: 100%; margin: 15px 0;">
            {rows_html}
        </table>
        <p style="color: grey; font-size: 12px; text-align: center;">
            This is an automated notification. Please do not reply.
        </p>
    </div>
</div>"""

    # =========================================================
    # DISPLAY NAME
    # =========================================================

    def _compute_display_name(self):
        for record in self:
            name = record.name or 'New'
            if record.subject:
                record.display_name = f"{name} - {record.subject}"
            else:
                record.display_name = name

    # =========================================================
    # DEFAULT EMPLOYEE
    # =========================================================

    def _get_current_employee(self):
        return self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)],
            limit=1
        )

    # =========================================================
    # COMPUTE LINE/IT MANAGER
    # =========================================================

    @api.depends('employee_id', 'employee_id.parent_id', 'employee_id.parent_id.user_id')
    def _compute_line_manager(self):
        for rec in self:
            if rec.employee_id and rec.employee_id.parent_id and rec.employee_id.parent_id.user_id:
                rec.line_manager_id = rec.employee_id.parent_id.user_id
            else:
                rec.line_manager_id = False

    @api.depends('department_id')
    def _compute_it_manager(self):
        it_manager = self._find_it_manager()
        for rec in self:
            rec.it_manager_id = it_manager if it_manager else False

    # =========================================================
    # CREATE (AUTO-SUBMIT FOR PORTAL USERS)
    # =========================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('it.ticket') or 'New'

        records = super().create(vals_list)

        for record in records:
            if record.env.user.has_group('base.group_portal'):
                if record.ticket_type == 'hardware':
                    record.action_submit_to_it_manager()
                else:
                    record.action_submit()

        return records

    # ===== NEW METHOD =====
    def action_submit_to_it_manager(self):
        """Hardware tickets go directly to IT Manager approval"""
        for rec in self:
            if not rec.it_manager_id:
                raise ValidationError(_("No IT Manager configured."))

            rec.write({
                'state': 'it_approval',
                'submitted_date': fields.Datetime.now(),
            })

            priority_label = dict(rec._fields['priority'].selection).get(rec.priority, rec.priority)
            type_label = dict(rec._fields['ticket_type'].selection).get(rec.ticket_type, rec.ticket_type)

            body = rec._build_ticket_email_body(
                header_color='#2980b9',
                header_title='&#128295; IT Manager Approval Required',
                button_color='#2980b9',
                button_url=f'/odoo/it-tickets/{rec.id}',
                recipient_name=rec.it_manager_id.name,
                intro_text='A hardware IT ticket has been submitted and requires your approval.',
                rows=[
                    ('Ticket Number', rec.name),
                    ('Subject', rec.subject),
                    ('Raised By', rec.employee_id.name),
                    ('Type', type_label),
                    ('Priority', priority_label),
                    ('Required By', str(rec.required_date) if rec.required_date else 'Not specified'),
                ],
            )
            rec._send_ticket_email(
                recipient_partner=rec.it_manager_id.partner_id,
                subject=f'IT Approval Required: {rec.name}',
                body=body,
            )

            rec.message_post(
                body=_("Hardware ticket submitted directly to IT Manager: %s") % rec.it_manager_id.name
            )

    def action_assign_to_it_team(self):
        """Assign Hardware tickets directly to IT Team (skip approvals)"""
        for rec in self:
            rec.write({
                'state': 'assigned',
                'submitted_date': fields.Datetime.now(),
            })

            body = rec._build_ticket_email_body(
                header_color='#27ae60',
                header_title='&#9989; Your Ticket Has Been Assigned',
                button_color='#27ae60',
                button_url=f'/my/tickets/{rec.id}',
                recipient_name=rec.employee_id.name,
                intro_text='Your IT ticket has been approved and assigned to the IT team. They will begin working on it shortly.',
                rows=[
                    ('Ticket Number', rec.name),
                    ('Subject', rec.subject),
                    ('Status', 'Assigned to IT Team'),
                    ('Priority', dict(rec._fields['priority'].selection).get(rec.priority, rec.priority)),
                ],
            )
            rec._send_ticket_email(
                recipient_partner=rec.employee_id.user_id.partner_id,
                subject=f'Your Ticket Has Been Assigned: {rec.name}',
                body=body,
            )

            rec.message_post(
                body=_("Hardware ticket automatically assigned to IT Team for immediate action.")
            )

    # =========================================================
    # WORKFLOW METHODS - APPROVE/REJECT
    # =========================================================

    def action_submit(self):
        """Submit ticket to line manager for approval"""
        for rec in self:
            if not rec.line_manager_id:
                raise ValidationError(
                    _("No line manager found for employee: %s") % rec.employee_id.name
                )

            rec.state = 'manager_approval'
            rec.submitted_date = fields.Datetime.now()

            priority_label = dict(rec._fields['priority'].selection).get(rec.priority, rec.priority)
            type_label = dict(rec._fields['ticket_type'].selection).get(rec.ticket_type, rec.ticket_type)

            body = rec._build_ticket_email_body(
                header_color='#2c3e50',
                header_title='&#127903; IT Ticket - Approval Required',
                button_color='#e67e22',
                button_url=f'/odoo/it-tickets/{rec.id}',
                recipient_name=rec.line_manager_id.name,
                intro_text='An IT ticket has been submitted by your team member and requires your approval.',
                rows=[
                    ('Ticket Number', rec.name),
                    ('Subject', rec.subject),
                    ('Raised By', rec.employee_id.name),
                    ('Type', type_label),
                    ('Priority', priority_label),
                    ('Required By', str(rec.required_date) if rec.required_date else 'Not specified'),
                ],
            )
            rec._send_ticket_email(
                recipient_partner=rec.line_manager_id.partner_id,
                subject=f'Action Required: IT Ticket Approval - {rec.name}',
                body=body,
            )

            rec.message_post(
                body=_("Ticket submitted to Line Manager: %s") % rec.line_manager_id.name
            )

    def action_manager_approve(self):
        self.ensure_one()
        if self.env.user != self.line_manager_id:
            _logger.info("self.line_manager_id: %s | self.env.user: %s | self.line_manager_id.user_id: %s",
                         self.line_manager_id, self.env.user, self.line_manager_id.user_id)
            raise UserError(
                _("Only the line manager (%s) can approve this ticket") % self.line_manager_id.name
            )
        return {
            'name': _('Approve Ticket'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.ticket.approve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id}
        }

    def action_it_approve(self):
        self.ensure_one()
        if not self.env.user.has_group('ticketing_it.group_it_manager'):
            raise UserError(_("Only IT managers can approve this ticket"))
        return {
            'name': _('Approve Ticket'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.ticket.approve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id}
        }

    def action_reject(self):
        """Open wizard to reject ticket with reason."""
        self.ensure_one()
        self._check_reject_access()
        return {
            'name': _('Reject Ticket'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.ticket.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id}
        }

    def _check_reject_access(self):
        self.ensure_one()
        user = self.env.user
        if self.state == 'manager_approval':
            if user != self.line_manager_id:
                raise UserError(
                    _("Only the line manager (%s) can reject this ticket.")
                    % (self.line_manager_id.name or _('unassigned'))
                )
        elif self.state == 'it_approval':
            if not user.has_group('ticketing_it.group_it_manager'):
                raise UserError(_("Only IT managers can reject this ticket."))
        else:
            raise UserError(
                _("This ticket cannot be rejected in its current state (%s).")
                % dict(self._fields['state'].selection).get(self.state, self.state)
            )

    def do_reject(self, reason):
        """Actually reject the ticket (called from wizard)."""
        for rec in self:
            rec._check_reject_access()

            rec.sudo().write({
                'state': 'rejected',
                'rejection_reason': reason,
                'rejected_by_id': self.env.user.id,
                'rejected_date': fields.Datetime.now(),
            })

            rec.activity_unlink(['mail.mail_activity_data_todo'])

            body = rec._build_ticket_email_body(
                header_color='#c0392b',
                header_title='&#10060; IT Ticket Rejected',
                button_color='#c0392b',
                button_url=f'/my/tickets/{rec.id}',
                recipient_name=rec.employee_id.name,
                intro_text='Unfortunately your IT ticket has been rejected.',
                rows=[
                    ('Ticket Number', rec.name),
                    ('Subject', rec.subject),
                    ('Rejected By', rec.rejected_by_id.name),
                    ('Rejection Date', str(rec.rejected_date)),
                    ('Reason', rec.rejection_reason or 'No reason provided'),
                ],
            )
            rec._send_ticket_email(
                recipient_partner=rec.employee_id.user_id.partner_id,
                subject=f'IT Ticket Rejected: {rec.name}',
                body=body,
            )

            rec.message_post(
                body=_("Ticket rejected by %s<br/>Reason: %s") % (self.env.user.name, reason)
            )

    # =========================================================
    # IT TEAM WORKFLOW
    # =========================================================

    def action_start_work(self):
        for rec in self:
            if rec.assigned_to_id != self.env.user:
                raise UserError(_("This ticket is not assigned to you."))
            rec.state = 'in_progress'
            rec.sudo().message_post(
                body=_("Work started by %s") % self.env.user.name
            )

    def action_done(self):
        """Mark ticket as done"""
        for rec in self:
            rec.state = 'done'
            rec.done_date = fields.Datetime.now()

            body = rec._build_ticket_email_body(
                header_color='#27ae60',
                header_title='&#127881; Your IT Ticket Is Resolved',
                button_color='#27ae60',
                button_url=f'/my/tickets/{rec.id}',
                recipient_name=rec.employee_id.name,
                intro_text='Your IT ticket has been resolved and completed.',
                rows=[
                    ('Ticket Number', rec.name),
                    ('Subject', rec.subject),
                    ('Completed On', str(rec.done_date)),
                    ('Resolved By', rec.assigned_to_id.name if rec.assigned_to_id else 'IT Team'),
                ],
            )
            rec._send_ticket_email(
                recipient_partner=rec.employee_id.user_id.partner_id,
                subject=f'IT Ticket Completed: {rec.name}',
                body=body,
            )

            rec.message_post(
                body=_("Ticket completed by %s and employee notified") % self.env.user.name
            )

    # =========================================================
    # 24 HOUR MANAGER REMINDER (CALLED BY SCHEDULED ACTION)
    # =========================================================

    def action_send_manager_reminder(self):
        if not self:
            pending_tickets = self.search([('state', '=', 'manager_approval')])
        else:
            pending_tickets = self

        _logger.info("24hr Reminder: Found %d tickets pending manager approval.", len(pending_tickets))

        for ticket in pending_tickets:
            try:
                if not ticket.employee_id:
                    continue
                if not ticket.line_manager_id:
                    continue
                if not ticket.line_manager_id.email:
                    continue

                manager = ticket.line_manager_id

                body = ticket._build_ticket_email_body(
                    header_color='#e74c3c',
                    header_title='&#9203; Approval Reminder',
                    button_color='#e74c3c',
                    button_url=f'/odoo/it-tickets/{ticket.id}',
                    recipient_name=manager.name,
                    intro_text='This is a <strong style="color: #e74c3c;">24-hour reminder</strong> that the following IT ticket is still pending your approval. You will continue receiving this reminder every 24 hours until you approve or reject.',
                    rows=[
                        ('Ticket Number', ticket.name),
                        ('Subject', ticket.subject),
                        ('Raised By', ticket.employee_id.name),
                        ('Submitted On', str(ticket.submitted_date)),
                        ('Last Reminder Sent', str(ticket.last_reminder_sent) if ticket.last_reminder_sent else 'First reminder'),
                    ],
                )
                ticket._send_ticket_email(
                    recipient_partner=manager.partner_id,
                    subject=f'Reminder: IT Ticket Awaiting Your Approval - {ticket.name}',
                    body=body,
                )

                ticket.sudo().write({'last_reminder_sent': fields.Datetime.now()})
                ticket.message_post(
                    body=_("24-hour reminder sent to line manager <strong>%s</strong> (%s).")
                         % (manager.name, manager.email),
                    message_type='notification',
                )

            except Exception as e:
                _logger.error("Failed to send 24hr reminder for ticket %s: %s", ticket.name, str(e))
                continue

    # =========================================================
    # PORTAL ACCESS URL
    # =========================================================

    def _compute_access_url(self):
        super()._compute_access_url()
        for ticket in self:
            ticket.access_url = '/my/tickets/%s' % ticket.id

    @api.depends('create_date', 'done_date')
    def _compute_resolution_time(self):
        for rec in self:
            if rec.create_date and rec.done_date:
                delta = rec.done_date - rec.create_date
                rec.resolution_time = delta.total_seconds() / 60
            else:
                rec.resolution_time = 0

    @api.depends('done_date')
    def _compute_month_solved(self):
        for rec in self:
            if rec.done_date:
                rec.month_solved = rec.done_date.strftime('%B %Y')
            else:
                rec.month_solved = 'N/A'

    @api.constrains('assigned_to_id')
    def _check_assigned_to_access(self):
        for rec in self:
            if rec.assigned_to_id:
                if not self.env.user.has_group('ticketing_it.group_it_manager'):
                    raise ValidationError(_("Only IT Managers can assign tickets."))

    # ===== HARD SECURITY =====
    def write(self, vals):
        if 'assigned_to_id' in vals:
            if not self.env.user.has_group('ticketing_it.group_it_manager'):
                raise AccessError("Only IT Manager can assign tickets.")

        if 'state' in vals:
            new_state = vals.get('state')
            now = fields.Datetime.now()
            for record in self:
                if new_state == 'manager_approval' and record.state != 'manager_approval':
                    vals['manager_approval_date'] = now
                if new_state == 'it_approval' and record.state != 'it_approval':
                    vals['it_approval_date'] = now

        return super().write(vals)

    def open_reminder_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'it.reminder.config.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_send_dynamic_reminder(self):
        _logger.info("===== CRON STARTED: IT Ticket Reminder =====")

        ICP = self.env['ir.config_parameter'].sudo()
        reminder_minutes = int(ICP.get_param('ticketing_it.reminder_days', 1))
        _logger.info("Reminder interval (minutes): %s", reminder_minutes)

        now = fields.Datetime.now()
        _logger.info("Current time: %s", now)

        tickets = self.search([('state', 'in', ['manager_approval', 'it_approval'])])
        _logger.info("Total tickets found in approval states: %s", len(tickets))

        user_ticket_map = defaultdict(list)

        for ticket in tickets:
            _logger.info("Checking Ticket: %s | State: %s", ticket.name, ticket.state)

            if ticket.state == 'manager_approval':
                state_date = ticket.manager_approval_date
                user = ticket.line_manager_id
            elif ticket.state == 'it_approval':
                state_date = ticket.it_approval_date
                user = ticket.it_manager_id
            else:
                continue

            if not state_date or not user:
                _logger.warning("Skipping ticket due to missing state_date or user")
                continue

            minutes_in_state = int((now - state_date).total_seconds() / 60)
            _logger.info("Minutes in state: %s", minutes_in_state)

            if minutes_in_state < reminder_minutes:
                _logger.info("Skipping - Not enough time passed")
                continue

            if ticket.last_reminder_sent:
                minutes_since_last = int((now - ticket.last_reminder_sent).total_seconds() / 60)
                if minutes_since_last < reminder_minutes:
                    _logger.info("Skipping - Reminder already sent recently")
                    continue

            user_ticket_map[user].append(ticket)

        _logger.info("Users to notify: %s", len(user_ticket_map))

        for user, user_tickets in user_ticket_map.items():
            _logger.info("Preparing email for user: %s", user.name)

            ticket_list_html = "<ul>"
            for ticket in user_tickets:
                ticket_list_html += f"<li>{ticket.name} — {ticket.subject or ''}</li>"
            ticket_list_html += "</ul>"

            body = f"""
<div style="font-family: Arial, sans-serif; padding: 20px; max-width: 600px; margin: 0 auto;">
    <div style="background-color: #e67e22; padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
        <h2 style="color: white; margin: 0;">&#9203; Pending Tickets Reminder</h2>
    </div>
    <div style="background-color: #fef9f0; padding: 30px; text-align: center;
                border-left: 1px solid #ddd; border-right: 1px solid #ddd;">
        <p style="margin: 0 0 20px 0; font-size: 15px; color: #555;">
            You have pending tickets waiting for your action
        </p>
        <a href="/odoo/it-tickets"
           style="display: inline-block; background-color: #e67e22; color: white;
                  text-decoration: none; padding: 20px 60px; border-radius: 8px;
                  font-size: 20px; font-weight: bold; letter-spacing: 1px;
                  box-shadow: 0 4px 10px rgba(0,0,0,0.2);">
            &#128065; VIEW IT SUPPORT TICKET
        </a>
    </div>
    <div style="border: 1px solid #ddd; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
        <p>Dear <strong>{user.name}</strong>,</p>
        <p>You have the following pending tickets to approve:</p>
        {ticket_list_html}
        <p style="color: grey; font-size: 12px; text-align: center;">
            This is an automated notification. Please do not reply.
        </p>
    </div>
</div>"""

            self.env['mail.mail'].sudo().create({
                'subject': 'Pending Ticket Reminder',
                'body_html': body,
                'email_to': user.partner_id.email,
                'recipient_ids': [(4, user.partner_id.id)],
            }).send()

            _logger.info("Email sent to: %s", user.name)

            for ticket in user_tickets:
                ticket.sudo().write({'last_reminder_sent': now})
                ticket.message_post(
                    body=_("Consolidated reminder sent to %s") % user.name
                )

        _logger.info("===== CRON FINISHED =====")