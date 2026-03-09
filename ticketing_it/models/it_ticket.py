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
        store=True,  # <-- important!
    )
    show_it_teams = fields.Boolean(
        string="Visible to IT team",
        compute="_compute_show_to_it_team",
        store=True,  # <-- important!
    )
    is_line_manager = fields.Boolean(compute="_compute_user_roles")
    is_it_manager = fields.Boolean(compute="_compute_user_roles")
    show_to_line_manager = fields.Boolean(
        compute="_compute_show_line_manager"
    )

    line_manager_user_id = fields.Many2one('res.users', string='Line Manager User')  # New field
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

    @api.depends(
        'submitted_date',
        'manager_approval_date',
        'it_approval_date',
        'done_date'
    )
    def _compute_processing_days(self):
        for rec in self:

            # Line Manager Days
            if rec.submitted_date and rec.manager_approval_date:
                delta = rec.manager_approval_date - rec.submitted_date
                rec.manager_processing_days = delta.total_seconds() / 86400
            else:
                rec.manager_processing_days = 0

            # IT Manager Days
            if rec.manager_approval_date and rec.it_approval_date:
                delta = rec.it_approval_date - rec.manager_approval_date
                rec.it_processing_days = delta.total_seconds() / 86400
            else:
                rec.it_processing_days = 0

            # IT Team Days
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
                rec.manager_processing_time = delta.total_seconds() / 3600  # in hours
                _logger.info(
                    "manager_processing_time: %s", rec.manager_processing_time
                )

            else:
                rec.manager_processing_time = 0

    @api.depends('manager_approval_date', 'it_approval_date')
    def _compute_it_processing_time(self):
        for rec in self:
            if rec.manager_approval_date and rec.it_approval_date:
                delta = rec.it_approval_date - rec.manager_approval_date
                rec.it_processing_time = delta.total_seconds() / 3600  # in hours
                _logger.info(
                    "it_manager_processing_time: %s", rec.it_processing_time
                )
            else:
                rec.it_processing_time = 0

    @api.depends('it_approval_date', 'done_date', 'state')
    def _compute_it_team_processing_time(self):
        for rec in self:
            # Only calculate if assigned/in_progress/done
            if rec.it_approval_date and rec.done_date:
                delta = rec.done_date - rec.it_approval_date
                rec.it_team_processing_time = delta.total_seconds() / 3600
                _logger.info(
                    "it_team_processing_time: %s", rec.it_team_processing_time
                )
            else:
                rec.it_team_processing_time = 0

    @api.depends('submitted_date', 'done_date')
    def _compute_total_resolution_time(self):
        for rec in self:
            if rec.submitted_date and rec.done_date:
                delta = rec.done_date - rec.submitted_date
                rec.total_resolution_time = delta.total_seconds() / 3600
                _logger.info(
                    "total_resolution_time: %s", rec.total_resolution_time
                )
            else:
                rec.total_resolution_time = 0
    @api.depends('employee_id')
    def _compute_show_line_manager(self):
        for ticket in self:
            _logger.info("Ticket: %s | Employee: %s", ticket.id,
                         ticket.employee_id.name if ticket.employee_id else None)
            if ticket.employee_id and ticket.employee_id.parent_id:
                manager_email = ticket.employee_id.parent_id.work_email
                _logger.info("Line Manager Email: %s", manager_email)
                if manager_email:
                    user = self.env['res.users'].search([('email', '=', manager_email)], limit=1)
                    if user:
                        _logger.info("Found user: %s | ID: %s", user.name, user.id)
                        ticket.line_manager_user_id = user.id
                    else:
                        _logger.warning("No user found with email: %s", manager_email)
                        ticket.line_manager_user_id = False
                else:
                    _logger.warning("Line manager has no email")
                    ticket.line_manager_user_id = False
            else:
                _logger.info("No employee or parent (line manager) for ticket")
                ticket.line_manager_user_id = False

    @api.depends('line_manager_id')
    def _compute_user_roles(self):
        for rec in self:
            # 🔍 DEBUG LOG
            _logger.info(
                "line_manager_id.user_id: %s | self.env.user: %s | rec.line_manager_id: %s",
                rec.line_manager_id.user_id,
                self.env.user,
                rec.line_manager_id,
            )
            rec.is_line_manager = (
                rec.line_manager_id == self.env.user
                if rec.line_manager_id
                else False
            )

            rec.is_it_manager = self.env.user.has_group(
                'ticketing_it.group_it_manager'
            )

            # 🔍 DEBUG LOG
            _logger.info(
                "Ticket: %s | User: %s | is_line_manager: %s | is_it_manager: %s",
                rec.name,
                self.env.user.name,
                rec.is_line_manager,
                rec.is_it_manager
            )

    @api.depends('state')
    def _compute_show_to_it_manager(self):
        for ticket in self:
            ticket.show_it_manager = ticket.state not in ['draft', 'manager_approval']
            # DEBUG LOGGING
            _logger.info("Ticket ID: %s | State: %s | Visible to IT Manager: %s",
                         ticket.id, ticket.state, ticket.show_it_manager)

    @api.depends('state')
    def _compute_show_to_it_team(self):
        for ticket in self:
            ticket.show_it_teams = ticket.state in ['assigned', 'done']
            _logger.info("Ticket ID: %s | State: %s | Visible to IT team: %s",
                         ticket.id, ticket.state, ticket.show_it_teams)
    @api.depends()
    def _compute_allowed_it_users(self):
        it_team_group = self.env.ref("ticketing_it.group_it_team")
        for ticket in self:
            ticket.allowed_it_users = it_team_group.user_ids

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
    # HELPER: FIND IT MANAGER VIA SQL
    # Uses raw SQL on res_groups_users_rel table.
    # This is the ONLY reliable method in all Odoo 17 versions.
    # groups_id domain search is broken in this Odoo build.
    # Admin assigns IT Manager in Settings → Users → Groups button.
    # No names or emails hardcoded anywhere.
    # =========================================================

    def _find_it_manager(self):
        """
        Find IT Manager user via direct SQL on the groups-users relation table.
        Works in all Odoo 17 versions — avoids the broken groups_id domain search.
        """
        it_manager_group = self.env.ref(
            'ticketing_it.group_it_manager',
            raise_if_not_found=False
        )
        if not it_manager_group:
            _logger.error(
                "IT Manager group 'ticketing_it.group_it_manager' not found. "
                "Check security/security.xml in your module."
            )
            return False

        # Direct SQL — bypasses the broken domain search entirely
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
            _logger.info(
                "IT Manager found via SQL: %s | Email: %s",
                user.name, user.email
            )
            return user

        _logger.warning(
            "No IT Manager found in group. "
            "Go to Settings → Users → [your IT manager user] → "
            "Groups button → Add 'IT Manager' group."
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
        """
        Get IT Manager via SQL — safe for all Odoo 17 versions.
        groups_id domain search is broken in this Odoo build, so we use SQL.
        """
        it_manager = self._find_it_manager()
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

            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=rec.it_manager_id.id,
                summary=_('Hardware Ticket Approval Required: %s') % rec.name,
                note=_('Hardware ticket submitted by %s. Please approve and assign.')
                     % rec.employee_id.name
            )

            rec.message_post(
                body=_("Hardware ticket submitted directly to IT Manager: %s")
                     % rec.it_manager_id.name
            )

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

    # def action_manager_approve(self):
    #     """Line manager approves ticket — sends email to IT manager"""
    #     for rec in self:
    #         if self.env.user != rec.line_manager_id:
    #             raise UserError(
    #                 _("Only the line manager (%s) can approve this ticket") % rec.line_manager_id.name
    #             )
    #
    #         rec.state = 'it_approval'
    #         rec.manager_approval_date = fields.Datetime.now()
    #
    #         rec.activity_unlink(['mail.mail_activity_data_todo'])
    #
    #         # Always re-fetch IT manager via SQL at approval time
    #         # This fixes old tickets where it_manager_id was empty
    #         if not rec.it_manager_id:
    #             it_manager = rec._find_it_manager()
    #             if it_manager:
    #                 rec.sudo().write({'it_manager_id': it_manager.id})
    #
    #         if rec.it_manager_id:
    #             template = self.env.ref(
    #                 'ticketing_it.email_template_it_approval',
    #                 raise_if_not_found=False
    #             )
    #             if template:
    #                 template.send_mail(rec.id, force_send=True)
    #                 _logger.info(
    #                     "IT approval email sent to %s (%s) for ticket %s",
    #                     rec.it_manager_id.name,
    #                     rec.it_manager_id.email,
    #                     rec.name
    #                 )
    #
    #             rec.activity_schedule(
    #                 'mail.mail_activity_data_todo',
    #                 user_id=rec.it_manager_id.id,
    #                 summary=_('IT Approval Required: %s') % rec.name,
    #                 note=_('Ticket approved by line manager. Please review.')
    #             )
    #
    #             rec.message_post(
    #                 body=_("Approved by Line Manager: %s. Sent to IT Manager: %s") % (
    #                     self.env.user.name,
    #                     rec.it_manager_id.name
    #                 )
    #             )
    #         else:
    #             rec.message_post(
    #                 body=_("Approved by Line Manager: %s. WARNING: No IT Manager found — "
    #                        "please assign a user to the IT Manager group.") % self.env.user.name
    #             )
    #
    # def action_it_approve(self):
    #     """IT manager approves ticket - assigns to IT team"""
    #     for rec in self:
    #         if not self.env.user.has_group('ticketing_it.group_it_manager'):
    #             raise UserError(_("Only IT managers can approve this ticket"))
    #         if not rec.assigned_to_id:
    #             raise ValidationError(
    #                 _("You must select 'Assigned To' before approving.")
    #             )
    #         rec.state = 'assigned'
    #         rec.it_approval_date = fields.Datetime.now()
    #
    #         rec.activity_unlink(['mail.mail_activity_data_todo'])
    #
    #         template = self.env.ref(
    #             'ticketing_it.email_template_it_assigned',
    #             raise_if_not_found=False
    #         )
    #         if template:
    #             template.send_mail(rec.id, force_send=True)
    #
    #         rec.message_post(
    #             body=_("Approved by IT Manager: %s. Assigned to IT Team.") % self.env.user.name
    #         )
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
        Called by scheduled action every 24 hours.
        Sends reminder email to line manager for pending tickets.
        FROM email read dynamically from Odoo Settings — never hardcoded.
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

    @api.depends('create_date', 'done_date')
    def _compute_resolution_time(self):
        for rec in self:
            if rec.create_date and rec.done_date:
                delta = rec.done_date - rec.create_date
                rec.resolution_time = delta.total_seconds() / (60)  # convert seconds to days
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
                    raise ValidationError(
                        _("Only IT Managers can assign tickets.")
                    )

    # ===== HARD SECURITY =====
    def write(self, vals):

        # ----------------------------
        # ASSIGNMENT SECURITY
        # ----------------------------
        if 'assigned_to_id' in vals:
            if not self.env.user.has_group('ticketing_it.group_it_manager'):
                raise AccessError("Only IT Manager can assign tickets.")

        # ----------------------------
        # STATE CHANGE DATE TRACKING
        # ----------------------------
        if 'state' in vals:
            new_state = vals.get('state')
            now = fields.Datetime.now()

            for record in self:
                # If moving to manager approval
                if new_state == 'manager_approval' and record.state != 'manager_approval':
                    vals['manager_approval_date'] = now

                # If moving to IT approval
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

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        user = self.env.user

        # ── Admins see everything ──────────────────────────────────────
        if user.has_group('base.group_system') or user.has_group('hr.group_hr_manager'):
            return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)

        # ── IT Manager ─────────────────────────────────────────────────
        # Sees ONLY tickets that physically reached IT stage
        # (it_approval_date is set = ticket passed line manager)
        # Rejected by line manager → it_approval_date is NULL → hidden
        if user.has_group('ticketing_it.group_it_manager'):
            it_domain = [
                ('it_approval_date', '!=', False),  # only tickets that reached IT stage
            ]
            return super()._search(domain + it_domain, offset=offset, limit=limit, order=order, **kwargs)

        # ── IT Team ────────────────────────────────────────────────────
        # Sees ONLY tickets assigned to them
        if user.has_group('ticketing_it.group_it_team'):
            it_team_domain = [('assigned_to_id', '=', user.id)]
            return super()._search(domain + it_team_domain, offset=offset, limit=limit, order=order, **kwargs)

        # ── Line Manager ───────────────────────────────────────────────
        # Sees ONLY tickets of their direct reports
        # that have NOT yet passed to IT stage
        # (manager_approval_date set but it_approval_date is NULL)
        employee = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
        managed_employees = self.env['hr.employee'].search([('parent_id', '=', employee.id)])

        if managed_employees:
            line_manager_domain = [
                ('employee_id', 'in', managed_employees.ids),
                ('it_approval_date', '=', False),  # not yet passed to IT manager
            ]
            own_tickets_domain = [('employee_id.user_id', '=', user.id)]
            combined_domain = ['|'] + line_manager_domain + own_tickets_domain
            return super()._search(domain + combined_domain, offset=offset, limit=limit, order=order, **kwargs)

        # ── Regular Employee ───────────────────────────────────────────
        # Sees ONLY their own tickets
        return super()._search(
            domain + [('employee_id.user_id', '=', user.id)],
            offset=offset, limit=limit, order=order, **kwargs
        )

    def action_send_dynamic_reminder(self):
        _logger.info("===== CRON STARTED: IT Ticket Reminder =====")

        ICP = self.env['ir.config_parameter'].sudo()
        reminder_minutes = int(ICP.get_param('ticketing_it.reminder_days', 1))
        _logger.info("Reminder interval (minutes): %s", reminder_minutes)

        now = fields.Datetime.now()
        _logger.info("Current time: %s", now)

        tickets = self.search([
            ('state', 'in', ['manager_approval', 'it_approval'])
        ])
        _logger.info("Total tickets found in approval states: %s", len(tickets))

        user_ticket_map = defaultdict(list)

        for ticket in tickets:
            _logger.info("Checking Ticket: %s | State: %s", ticket.name, ticket.state)

            if ticket.state == 'manager_approval':
                _logger.info("Manager approval date %s", ticket.manager_approval_date)
                state_date = ticket.manager_approval_date
                user = ticket.line_manager_id
                _logger.info("ticket.line_manager_id %s", ticket.line_manager_id)

            elif ticket.state == 'it_approval':
                _logger.info("IT Manager approval date %s", ticket.it_approval_date)
                state_date = ticket.it_approval_date
                user = ticket.it_manager_id

            else:
                continue

            if not state_date or not user:
                _logger.warning("Skipping ticket due to missing state_date or user")
                continue

            # Compute minutes only (ignore seconds)
            minutes_in_state = int((now - state_date).total_seconds() / 60)
            _logger.info("Minutes in state: %s", minutes_in_state)
            _logger.info("reminder_minutes: %s", reminder_minutes)
            # Check if reminder threshold is reached
            if minutes_in_state < reminder_minutes:
                _logger.info("Skipping - Not enough time passed")
                continue
            _logger.info("ticket.last_reminder_sent: %s", ticket.last_reminder_sent)
            if ticket.last_reminder_sent:
                minutes_since_last = int((now - ticket.last_reminder_sent).total_seconds() / 60)
                _logger.info("Minutes since last reminder: %s", minutes_since_last)

                if minutes_since_last < reminder_minutes:
                    _logger.info("Skipping - Reminder already sent recently")
                    continue

            _logger.info("Adding ticket to user group: %s", user.name)
            user_ticket_map[user].append(ticket)

        _logger.info("Users to notify: %s", len(user_ticket_map))

        for user, user_tickets in user_ticket_map.items():
            _logger.info("Preparing email for user: %s", user.name)

            ticket_list_html = "<ul>"
            for ticket in user_tickets:
                ticket_list_html += f"<li>{ticket.name}</li>"
            ticket_list_html += "</ul>"

            body = f"""
                    <p>Dear {user.name},</p>
                    <p>You have pending tickets to approve:</p>
                    {ticket_list_html}
                """

            mail_values = {
                'subject': 'Pending Ticket Reminder',
                'body_html': body,
                'email_to': user.partner_id.email,
            }

            _logger.info("Creating email for: %s | Email: %s", user.name, user.partner_id.email)

            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()

            _logger.info("Email sent to: %s", user.name)

            for ticket in user_tickets:
                ticket.sudo().write({
                    'last_reminder_sent': now
                })

                ticket.message_post(
                    body=_("Consolidated reminder sent to %s") % user.name
                )

        _logger.info("===== CRON FINISHED =====")
