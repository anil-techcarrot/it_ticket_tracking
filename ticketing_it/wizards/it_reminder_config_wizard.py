from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ITReminderConfigWizard(models.TransientModel):
    _name = 'it.reminder.config.wizard'
    _description = 'IT Reminder Configuration Wizard'

    reminder_days = fields.Integer(
        string="Reminder Interval (Minutes)",
        required=True,
        default=1
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ICP = self.env['ir.config_parameter'].sudo()
        saved_days = ICP.get_param('ticketing_it.reminder_days')
        res['reminder_days'] = int(saved_days) if saved_days else 1
        return res

    def action_save(self):
        if self.reminder_days <= 0:
            raise ValidationError(_("Reminder days must be greater than 0."))

        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('ticketing_it.reminder_days', self.reminder_days)

        return {'type': 'ir.actions.act_window_close'}