from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo import fields as odoo_fields
import logging

_logger = logging.getLogger(__name__)


class ItTicketApproveWizard(models.TransientModel):
    _name = 'it.ticket.approve.wizard'
    _description = 'Approve Ticket Wizard'

    ticket_id = fields.Many2one('it.ticket', required=True)
    comment = fields.Text(string='Comment')
    approval_type = fields.Selection([
        ('manager', 'Line Manager'),
        ('it', 'IT Manager')
    ])

    def approve_ticket(self):
        self.ensure_one()

        rec = self.ticket_id

        _logger.info("===== APPROVAL STARTED =====")
        _logger.info("Wizard ID: %s", self.id)
        _logger.info("Approval Type: %s", self.approval_type)
        _logger.info("Current User: %s (ID: %s)", self.env.user.name, self.env.user.id)
        _logger.info("Ticket: %s (ID: %s)", rec.name, rec.id)
        _logger.info("Ticket Current State: %s", rec.state)
        _logger.info("Ticket Current State: %s", rec.line_manager_id)
        # =====================================================
        # LINE MANAGER APPROVAL
        # =====================================================
        if rec.state == 'manager_approval':

            _logger.info("Processing Line Manager Approval")

            if self.env.user != rec.line_manager_id:
                _logger.error("User is NOT the line manager")
                raise UserError(_("Only the Line Manager can approve this ticket."))

            rec.state = 'it_approval'
            rec.manager_approval_date = odoo_fields.Datetime.now()

            _logger.info("State changed to it_approval")

            rec.activity_unlink(['mail.mail_activity_data_todo'])
            _logger.info("Existing activities removed")

            if not rec.it_manager_id:
                _logger.info("No IT Manager set. Attempting to fetch via _find_it_manager()")
                it_manager = rec._find_it_manager()
                if it_manager:
                    rec.sudo().write({'it_manager_id': it_manager.id})
                    _logger.info("IT Manager assigned: %s", it_manager.name)
                else:
                    _logger.warning("No IT Manager found from _find_it_manager()")

            if rec.it_manager_id:
                _logger.info("Sending email to IT Manager: %s", rec.it_manager_id.email)

                template = self.env.ref(
                    'ticketing_it.email_template_it_approval',
                    raise_if_not_found=False
                )

                if template:
                    template.send_mail(rec.id, force_send=True)
                    _logger.info("IT Approval email sent successfully")
                else:
                    _logger.warning("IT Approval email template not found")

                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=rec.it_manager_id.id,
                    summary=_('IT Approval Required: %s') % rec.name,
                    note=_('Ticket approved by line manager. Please review.')
                )

                _logger.info("Activity scheduled for IT Manager")

                message_body = _(
                    "Approved by Line Manager: %s<br/>"
                    "Sent to IT Manager: %s"
                ) % (self.env.user.name, rec.it_manager_id.name)

            else:
                message_body = _(
                    "Approved by Line Manager: %s<br/>"
                    "<b>WARNING:</b> No IT Manager found."
                ) % self.env.user.name

        # =====================================================
        # IT MANAGER APPROVAL
        # =====================================================
        # elif rec.state == 'it_approval':
        #
        #     _logger.info("Processing IT Manager Approval")
        #
        #     if not self.env.user.has_group('ticketing_it.group_it_manager'):
        #         _logger.error("User does NOT belong to IT Manager group")
        #         raise UserError(_("Only IT managers can approve this ticket"))
        #
        #     if not rec.assigned_to_id:
        #         _logger.error("Assigned To is missing")
        #         raise ValidationError(
        #             _("You must select 'Assigned To' before approving.")
        #         )
        #
        #     rec.state = 'assigned'
        #     rec.it_approval_date = odoo_fields.Datetime.now()
        #
        #     _logger.info("State changed to assigned")
        #
        #     rec.activity_unlink(['mail.mail_activity_data_todo'])
        #     _logger.info("Existing activities removed")
        #
        #     template = self.env.ref(
        #         'ticketing_it.email_template_it_assigned',
        #         raise_if_not_found=False
        #     )
        #
        #     if template:
        #         template.send_mail(rec.id, force_send=True)
        #         _logger.info("Assigned email sent successfully")
        #     else:
        #         _logger.warning("Assigned email template not found")
        #
        #     message_body = _(
        #         "Approved by IT Manager: %s<br/>"
        #         "Assigned to %s in IT Team."
        #     ) % (self.env.user.name, rec.assigned_to_id.name)
        elif rec.state == 'it_approval':

            _logger.info("Processing IT Manager Approval")

            # ✅ Check IT Manager group
            if not self.env.user.has_group('ticketing_it.group_it_manager'):
                _logger.error("User does NOT belong to IT Manager group")
                raise UserError(_("Only IT managers can approve this ticket"))

            # ✅ Auto-assign if not assigned
            if not rec.assigned_to_id:
                _logger.warning("Assigned To is missing. Fetching from IT Team group")

                it_team = self.env.ref('ticketing_it.group_it_team', raise_if_not_found=False)

                if it_team and it_team.user_ids:
                    rec.assigned_to_id = it_team.user_ids[0].id
                    _logger.info("Auto-assigned to: %s", rec.assigned_to_id.name)
                else:
                    _logger.error("No users found in IT Team group")
                    raise ValidationError(_("No users found in IT Team to assign."))

            # ✅ Update state
            rec.write({
                'state': 'assigned',
                'it_approval_date': fields.Datetime.now(),
            })

            _logger.info("State changed to assigned")

            # ✅ Remove previous activities
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            _logger.info("Existing activities removed")

            # ✅ Send email
            template = self.env.ref(
                'ticketing_it.email_template_it_assigned',
                raise_if_not_found=False
            )

            if template:
                template.send_mail(rec.id, force_send=True)
                _logger.info("Assigned email sent successfully")
            else:
                _logger.warning("Assigned email template not found")

            # ✅ Chatter message
            message_body = _(
                "Approved by IT Manager: %s<br/>"
                "Assigned to %s in IT Team."
            ) % (self.env.user.name, rec.assigned_to_id.name)
        else:
            _logger.error("Invalid approval type received: %s", self.approval_type)
            raise UserError(_("Invalid approval type."))

        # =====================================================
        # POST COMMENT TO CHATTER
        # =====================================================
        if self.comment:
            _logger.info("Adding comment to chatter")
            message_body += "<br/><b>Comment:</b> %s" % self.comment

        rec.message_post(
            body=message_body,
            body_is_html=True,
            author_id=self.env.user.partner_id.id,
            subtype_xmlid='mail.mt_comment'
        )

        _logger.info("Chatter message posted successfully")
        _logger.info("===== APPROVAL COMPLETED =====")

        return {'type': 'ir.actions.act_window_close'}