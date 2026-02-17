# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


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

    # ======================
    # REJECTION
    # ======================

    rejection_reason = fields.Text(readonly=True, string='Rejection Reason')
    rejected_by_id = fields.Many2one('res.users', readonly=True, string='Rejected By')
    rejected_date = fields.Datetime(readonly=True, string='Rejection Date')

    # =========================================================
    # DISPLAY NAME
    # =========================================================

    def _compute_display_name(self):
        """Odoo 19 uses _compute_display_name instead of name_get"""
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
                record.action_submit()

        return records

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
    # PORTAL ACCESS URL
    # =========================================================

    def _compute_access_url(self):
        """Portal URL for employees to view their tickets"""
        super()._compute_access_url()
        for ticket in self:
            ticket.access_url = '/my/tickets/%s' % ticket.id