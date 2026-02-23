# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
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

    assigned_to_id = fields.Many2one('res.users', string='Assigned To')

    # ======================
    # DATES
    # ======================

    submitted_date = fields.Datetime(readonly=True, string='Submitted Date')
    manager_approval_date = fields.Datetime(readonly=True, string='Manager Approval Date')
    it_approval_date = fields.Datetime(readonly=True, string='IT Approval Date')
    done_date = fields.Datetime(readonly=True, string='Completion Date')

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

    def _get_from_email(self):
        """
        Get central FROM email from Odoo settings.
        Admin sets once in Settings → General Settings → Default From Email.
        Never hardcoded in code.
        """
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
    # HELPER: GET IT MANAGER USER
    # Searches by group membership — reliable method
    # Admin assigns user to IT Manager group in Settings → Users
    # =========================================================

    def _get_it_manager_user(self):
        """
        Find the IT Manager user by searching group membership directly.
        This is more reliable than env.ref().user_ids.

        Admin assigns IT Manager in:
          Settings → Users → [user] → Groups button → Add IT Manager group
        No email or name hardcoded anywhere.
        """
        # Search users who belong to the IT Manager group directly
        it_manager_group = self.env.ref(
            'ticketing_it.group_it_manager',
            raise_if_not_found=False
        )

        if it_manager_group:
            # Direct search via groups_id — most reliable method
            it_manager_users = self.env['res.users'].sudo().search([
                ('groups_id', 'in', [it_manager_group.id]),
                ('active', '=', True),
                ('share', '=', False),  # internal users only, not portal
            ], limit=1)

            if it_manager_users:
                _logger.info(
                    "IT Manager found: %s | Email: %s",
                    it_manager_users.name,
                    it_manager_users.email
                )
                return it_manager_users
            else:
                _logger.warning(
                    "IT Manager group exists but has NO internal users assigned. "
                    "Go to Settings → Users → Jane Smith → Groups → Add IT Manager."
                )
        else:
            _logger.warning(
                "IT Manager group 'ticketing_it.group_it_manager' not found. "
                "Check your module security/security.xml file."
            )

        # Fallback: search by job title
        it_employee = self.env['hr.employee'].sudo().search([
            ('job_title', 'ilike', 'IT Manager'),
            ('user_id', '!=', False),
            ('user_id.active', '=', True),
        ], limit=1)

        if it_employee and it_employee.user_id:
            _logger.info(
                "IT Manager found via job title fallback: %s | Email: %s",
                it_employee.user_id.name,
                it_employee.user_id.email
            )
            return it_employee.user_id

        _logger.error(
            "No IT Manager found by any method. "
            "Please assign Jane Smith to the IT Manager group."
        )
        return False

    # =========================================================
    # DISPLAY NAME
    # =========================================================

    def _compute_display_name(self):
        """Odoo 17+ uses _compute_display_name instead of name_get"""
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
        """Get current user's employee record"""
        return self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)],
            limit=1
        )

    # =========================================================
    # COMPUTE METHODS
    # =========================================================

    @api.depends('employee_id', 'employee_id.parent_id', 'employee_id.parent_id.user_id')
    def _compute_line_manager(self):
        """Compute line manager from employee's parent"""
        for rec in self:
            if rec.employee_id and rec.employee_id.parent_id and rec.employee_id.parent_id.user_id:
                rec.line_manager_id = rec.employee_id.parent_id.user_id
            else:
                rec.line_manager_id = False

    @api.depends('department_id')
    def _compute_it_manager(self):
        """Get IT Manager from IT Manager security group — Odoo 17 compatible"""
        it_manager = False
        it_manager_group = self.env.ref(
            'ticketing_it.group_it_manager',
            raise_if_not_found=False
        )
        if it_manager_group:
            # Odoo 17+: access users via group.users (not searchable domain)
            active_users = it_manager_group.sudo().users.filtered(
                lambda u: u.active and not u.share
            )
            if active_users:
                it_manager = active_users[0]
        for rec in self:
            rec.it_manager_id = it_manager if it_manager else False

    # =========================================================
    # CREATE (AUTO-SUBMIT FOR PORTAL USERS)
    # =========================================================

    @api.model_create_multi
    def create(self, vals_list):
        """Create ticket and auto-submit for portal users"""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('it.ticket') or 'New'

        records = super().create(vals_list)

        for record in records:
            if record.env.user.has_group('base.group_portal'):
                if record.ticket_type == 'hardware':
                    record.action_assign_to_it_team()
                else:
                    record.action_submit()

        return records

    def action_assign_to_it_team(self):
        """Assign Hardware tickets directly to IT Team (skip approvals)"""
        for rec in self:
            rec.write({
                'state': 'assigned',
                'submitted_date': fields.Datetime.now(),
            })

            template = self.env.ref(
                'ticketing_it.email_template_it_assigned',
                raise_if_not_found=False
            )
            if template:
                template.send_mail(rec.id, force_send=True)

            if rec.it_manager_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=rec.it_manager_id.id,
                    summary=_('Hardware Ticket - Assign to IT Team: %s') % rec.name,
                    note=_('Hardware issue reported by %s. Please assign to IT team member.') % rec.employee_id.name
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

            template = self.env.ref(
                'ticketing_it.email_template_manager_approval',
                raise_if_not_found=False
            )
            if template:
                template.send_mail(rec.id, force_send=True)

            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=rec.line_manager_id.id,
                summary=_('Ticket Approval Required: %s') % rec.name,
                note=_('Please review and approve IT ticket from %s') % rec.employee_id.name
            )

            rec.message_post(
                body=_("Ticket submitted to Line Manager: %s") % rec.line_manager_id.name
            )

    def action_manager_approve(self):
        """
        Line manager approves ticket — sends email to IT manager.
        KEY FIX: Re-fetches IT manager at approval time using _get_it_manager_user()
        so even old tickets with empty it_manager_id will work correctly.
        """
        for rec in self:
            if self.env.user != rec.line_manager_id:
                raise UserError(
                    _("Only the line manager (%s) can approve this ticket") % rec.line_manager_id.name
                )

            rec.state = 'it_approval'
            rec.manager_approval_date = fields.Datetime.now()

            rec.activity_unlink(['mail.mail_activity_data_todo'])

            # KEY FIX: Always re-fetch IT manager at approval time
            # This fixes old tickets where it_manager_id was empty
            it_manager = rec._get_it_manager_user()
            if it_manager and not rec.it_manager_id:
                rec.sudo().write({'it_manager_id': it_manager.id})

            # Use the freshly fetched manager for sending email
            effective_it_manager = rec.it_manager_id or it_manager

            if not effective_it_manager:
                _logger.error(
                    "Cannot send IT approval email for ticket %s — "
                    "no IT Manager found. Please assign a user to IT Manager group.",
                    rec.name
                )
                rec.message_post(
                    body=_("WARNING: No IT Manager found. Please assign a user "
                           "to the IT Manager group in Settings → Users.")
                )
            else:
                template = self.env.ref(
                    'ticketing_it.email_template_it_approval',
                    raise_if_not_found=False
                )
                if template:
                    template.send_mail(rec.id, force_send=True)
                    _logger.info(
                        "IT approval email sent → Manager: %s | Email: %s | Ticket: %s",
                        effective_it_manager.name,
                        effective_it_manager.email,
                        rec.name
                    )

                if effective_it_manager:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=effective_it_manager.id,
                        summary=_('IT Approval Required: %s') % rec.name,
                        note=_('Ticket approved by line manager. Please review.')
                    )

            rec.message_post(
                body=_("Approved by Line Manager: %s. Sent to IT Manager: %s") % (
                    self.env.user.name,
                    effective_it_manager.name if effective_it_manager else 'NOT FOUND'
                )
            )

    def action_it_approve(self):
        """IT manager approves ticket - assigns to IT team"""
        for rec in self:
            if not self.env.user.has_group('ticketing_it.group_it_manager'):
                raise UserError(_("Only IT managers can approve this ticket"))

            rec.state = 'assigned'
            rec.it_approval_date = fields.Datetime.now()

            rec.activity_unlink(['mail.mail_activity_data_todo'])

            template = self.env.ref(
                'ticketing_it.email_template_it_assigned',
                raise_if_not_found=False
            )
            if template:
                template.send_mail(rec.id, force_send=True)

            rec.message_post(
                body=_("Approved by IT Manager: %s. Assigned to IT Team.") % self.env.user.name
            )

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
        """Verify the current user is allowed to reject this ticket."""
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

            template = self.env.ref(
                'ticketing_it.email_template_rejection',
                raise_if_not_found=False
            )
            if template:
                template.send_mail(rec.id, force_send=True)

            rec.message_post(
                body=_("Ticket rejected by %s<br/>Reason: %s") % (self.env.user.name, reason)
            )

    # =========================================================
    # IT TEAM WORKFLOW
    # =========================================================

    def action_start_work(self):
        """IT team starts working on ticket"""
        for rec in self:
            rec.state = 'in_progress'
            rec.assigned_to_id = self.env.user
            rec.message_post(
                body=_("Work started by %s") % self.env.user.name
            )

    def action_done(self):
        """Mark ticket as done"""
        for rec in self:
            rec.state = 'done'
            rec.done_date = fields.Datetime.now()

            template = self.env.ref(
                'ticketing_it.email_template_done',
                raise_if_not_found=False
            )
            if template:
                template.send_mail(rec.id, force_send=True)

            rec.message_post(
                body=_("Ticket completed by %s and employee notified") % self.env.user.name
            )

    # =========================================================
    # 24 HOUR MANAGER REMINDER (CALLED BY SCHEDULED ACTION)
    # =========================================================

    def action_send_manager_reminder(self):
        """
        Called by the scheduled action every 24 hours.
        Sends reminder email to line manager for pending tickets.
        FROM email is read dynamically from Odoo Settings — never hardcoded.
        """
        if not self:
            pending_tickets = self.search([('state', '=', 'manager_approval')])
        else:
            pending_tickets = self

        _logger.info(
            "24hr Reminder: Found %d tickets pending manager approval.",
            len(pending_tickets)
        )

        for ticket in pending_tickets:
            try:
                if not ticket.employee_id:
                    continue
                if not ticket.line_manager_id:
                    continue
                if not ticket.line_manager_id.email:
                    continue

                manager = ticket.line_manager_id

                template = self.env.ref(
                    'ticketing_it.email_template_manager_reminder_24hr',
                    raise_if_not_found=False
                )

                if template:
                    template.send_mail(ticket.id, force_send=True)
                    _logger.info(
                        "24hr reminder sent → Ticket: %s | Manager: %s (%s)",
                        ticket.name, manager.name, manager.email
                    )
                else:
                    from_email = ticket._get_from_email()
                    mail_values = {
                        'subject': _('Reminder: IT Ticket Awaiting Your Approval - %s') % ticket.name,
                        'body_html': '''
                            <div style="font-family: Arial, sans-serif; padding: 20px;">
                                <h2 style="color: #e74c3c;">Approval Reminder</h2>
                                <p>Dear <strong>{manager}</strong>,</p>
                                <p>Ticket <strong>{name}</strong> raised by
                                <strong>{employee}</strong> is still pending your approval.</p>
                                <p>Please log in and approve or reject immediately.</p>
                                <p style="color:grey; font-size:12px;">
                                    You will receive this reminder every 24 hours
                                    until you take action.
                                </p>
                            </div>
                        '''.format(
                            manager=manager.name,
                            name=ticket.name,
                            employee=ticket.employee_id.name,
                        ),
                        'email_to': manager.email,
                        'email_from': from_email,
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send()

                ticket.sudo().write({'last_reminder_sent': fields.Datetime.now()})
                ticket.message_post(
                    body=_(
                        "24-hour reminder sent to line manager <strong>%s</strong> (%s)."
                    ) % (manager.name, manager.email),
                    message_type='notification',
                )

            except Exception as e:
                _logger.error(
                    "Failed to send 24hr reminder for ticket %s: %s",
                    ticket.name, str(e)
                )
                continue

    # =========================================================
    # PORTAL ACCESS URL
    # =========================================================

    def _compute_access_url(self):
        """Portal URL for employees to view their tickets"""
        super()._compute_access_url()
        for ticket in self:
            ticket.access_url = '/my/tickets/%s' % ticket.id