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

    # Tracks when the last 24hr reminder was sent to line manager
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
    # No email is hardcoded — admin configures it in UI only
    # Settings → General Settings → Default From Email
    # =========================================================

    def _get_from_email(self):
        """
        Get the central FROM email dynamically from Odoo system settings.
        Admin sets this once in:
          Settings → General Settings → Default From Email
        No email address is ever hardcoded in the code.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        default_from = ICP.get_param('mail.default.from')
        catchall_domain = ICP.get_param('mail.catchall.domain')

        if default_from:
            # If domain is set, combine them properly
            if catchall_domain and '@' not in default_from:
                return '{}@{}'.format(default_from, catchall_domain)
            return default_from

        # Final fallback: use the company email
        company_email = self.env.company.email
        if company_email:
            return company_email

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
        """Get IT Manager from IT Manager security group"""
        for rec in self:
            it_manager_group = self.env.ref(
                'ticketing_it.group_it_manager',
                raise_if_not_found=False
            )
            if it_manager_group and it_manager_group.user_ids:
                rec.it_manager_id = it_manager_group.user_ids[0]
            else:
                rec.it_manager_id = False

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
                # Hardware tickets go DIRECTLY to IT Team (skip approvals)
                if record.ticket_type == 'hardware':
                    record.action_assign_to_it_team()
                else:
                    # All other tickets go through approval workflow
                    record.action_submit()

        return records

    def action_assign_to_it_team(self):
        """Assign Hardware tickets directly to IT Team (skip approvals)"""
        for rec in self:
            rec.write({
                'state': 'assigned',
                'submitted_date': fields.Datetime.now(),
            })

            # Send notification to IT Team
            template = self.env.ref(
                'ticketing_it.email_template_it_assigned',
                raise_if_not_found=False
            )
            if template:
                template.send_mail(rec.id, force_send=True)

            # Create activity for IT Manager to assign the ticket
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
        """Line manager approves ticket - sends to IT manager"""
        for rec in self:
            if self.env.user != rec.line_manager_id:
                raise UserError(
                    _("Only the line manager (%s) can approve this ticket") % rec.line_manager_id.name
                )

            rec.state = 'it_approval'
            rec.manager_approval_date = fields.Datetime.now()

            rec.activity_unlink(['mail.mail_activity_data_todo'])

            template = self.env.ref(
                'ticketing_it.email_template_it_approval',
                raise_if_not_found=False
            )
            if template and rec.it_manager_id:
                template.send_mail(rec.id, force_send=True)

            if rec.it_manager_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=rec.it_manager_id.id,
                    summary=_('IT Approval Required: %s') % rec.name,
                    note=_('Ticket approved by line manager. Please review.')
                )

            rec.message_post(
                body=_("Approved by Line Manager: %s. Sent to IT Manager.") % self.env.user.name
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
        """Open wizard to reject ticket with reason.

        FIX: The wizard model (it.ticket.reject.wizard) previously had no ACL
        rules, so any non-admin user clicking Reject got an Access Denied error
        when Odoo tried to load the wizard form view.

        Security is enforced inside do_reject() instead — only the assigned
        line manager (for manager_approval state) or an IT manager
        (for it_approval state) may actually complete the rejection.
        """
        self.ensure_one()

        # Check that the current user is actually allowed to reject
        # before even opening the wizard, so they get a clear message.
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
        """Verify the current user is allowed to reject this ticket.

        - In state 'manager_approval': only the assigned line manager may reject.
        - In state 'it_approval': only IT managers may reject.
        - Other states: no one may reject via this button.
        """
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
        """Actually reject the ticket (called from wizard).

        FIX: Use sudo() when writing rejection fields because the wizard
        runs under the calling user's rights, and those fields are marked
        readonly in the view/field definition.  sudo() is safe here because
        access has already been validated by _check_reject_access() before
        the wizard was opened.
        """
        for rec in self:
            # Re-validate in case someone calls do_reject directly
            rec._check_reject_access()

            rec.sudo().write({
                'state': 'rejected',
                'rejection_reason': reason,
                'rejected_by_id': self.env.user.id,
                'rejected_date': fields.Datetime.now(),
            })

            # Clear pending activities
            rec.activity_unlink(['mail.mail_activity_data_todo'])

            # Send rejection email to the employee (portal user)
            template = self.env.ref(
                'ticketing_it.email_template_rejection',
                raise_if_not_found=False
            )
            if template:
                template.send_mail(rec.id, force_send=True)

            # Log in chatter
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
        Sends a reminder email to the line manager for every ticket
        that is still in 'manager_approval' state.
        Reminder stops automatically when manager approves or rejects.

        FROM email is read dynamically from Odoo Settings.
        No email address is hardcoded here.
        Admin configures it once in:
          Settings → General Settings → Default From Email
        """
        # When called from scheduled action, self is empty — search all pending
        if not self:
            pending_tickets = self.search([
                ('state', '=', 'manager_approval'),
            ])
        else:
            pending_tickets = self

        _logger.info(
            "24hr Reminder: Found %d tickets pending manager approval.",
            len(pending_tickets)
        )

        for ticket in pending_tickets:
            try:
                # ── Safety Checks ─────────────────────────────────────────────

                if not ticket.employee_id:
                    _logger.warning(
                        "Ticket %s: No employee linked. Skipping reminder.",
                        ticket.name
                    )
                    continue

                if not ticket.line_manager_id:
                    _logger.warning(
                        "Ticket %s: Employee %s has no line manager. Skipping.",
                        ticket.name, ticket.employee_id.name
                    )
                    continue

                if not ticket.line_manager_id.email:
                    _logger.warning(
                        "Ticket %s: Line manager %s has no email. Skipping.",
                        ticket.name, ticket.line_manager_id.name
                    )
                    continue

                manager = ticket.line_manager_id

                # ── Send Email Using Template ─────────────────────────────────

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
                    # ── Fallback: Send Without Template ───────────────────────
                    # FROM email is read from Odoo settings — never hardcoded
                    from_email = ticket._get_from_email()

                    mail_values = {
                        'subject': _('Reminder: IT Ticket Awaiting Your Approval - %s') % ticket.name,
                        'body_html': '''
                            <div style="font-family: Arial, sans-serif; padding: 20px;">
                                <div style="background-color: #e74c3c; padding: 15px;
                                            border-radius: 5px; margin-bottom: 20px;">
                                    <h2 style="color: white; margin: 0;">
                                        Approval Reminder
                                    </h2>
                                </div>
                                <p>Dear <strong>{manager}</strong>,</p>
                                <p>This is a <strong>24-hour reminder</strong> that the
                                following IT ticket is still pending your approval.</p>
                                <table style="border-collapse: collapse; width: 100%;">
                                    <tr style="background:#f2f2f2;">
                                        <td style="padding:8px; border:1px solid #ddd; width:35%;">
                                            <strong>Ticket Number</strong>
                                        </td>
                                        <td style="padding:8px; border:1px solid #ddd;">
                                            {name}
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding:8px; border:1px solid #ddd;">
                                            <strong>Subject</strong>
                                        </td>
                                        <td style="padding:8px; border:1px solid #ddd;">
                                            {subject}
                                        </td>
                                    </tr>
                                    <tr style="background:#f2f2f2;">
                                        <td style="padding:8px; border:1px solid #ddd;">
                                            <strong>Raised By</strong>
                                        </td>
                                        <td style="padding:8px; border:1px solid #ddd;">
                                            {employee}
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding:8px; border:1px solid #ddd;">
                                            <strong>Priority</strong>
                                        </td>
                                        <td style="padding:8px; border:1px solid #ddd;">
                                            {priority}
                                        </td>
                                    </tr>
                                    <tr style="background:#f2f2f2;">
                                        <td style="padding:8px; border:1px solid #ddd;">
                                            <strong>Submitted On</strong>
                                        </td>
                                        <td style="padding:8px; border:1px solid #ddd;">
                                            {submitted}
                                        </td>
                                    </tr>
                                </table>
                                <p>Please log in and <strong>Approve or Reject</strong>
                                this ticket immediately.</p>
                                <p style="color:grey; font-size:12px;">
                                    You will receive this reminder every 24 hours
                                    until you take action on this ticket.
                                </p>
                            </div>
                        '''.format(
                            manager=manager.name,
                            name=ticket.name,
                            subject=ticket.subject or 'N/A',
                            employee=ticket.employee_id.name,
                            priority=dict(
                                ticket._fields['priority'].selection
                            ).get(ticket.priority, ticket.priority),
                            submitted=str(ticket.submitted_date or ticket.create_date),
                        ),
                        'email_to': manager.email,
                        'email_from': from_email,  # ← from Odoo settings, not hardcoded
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send()
                    _logger.info(
                        "Fallback 24hr reminder sent → Ticket: %s | Manager: %s",
                        ticket.name, manager.name
                    )

                # ── Update Timestamp & Log in Chatter ────────────────────────

                ticket.sudo().write({
                    'last_reminder_sent': fields.Datetime.now()
                })

                ticket.message_post(
                    body=_(
                        "24-hour reminder sent to line manager "
                        "<strong>%s</strong> (%s) for approval."
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