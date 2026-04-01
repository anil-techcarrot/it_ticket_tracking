# -*- coding: utf-8 -*-
from odoo import models


class AccountMoveSequenceBypass(models.Model):
    _inherit = 'account.move'

    def _must_check_constrains_date_sequence(self):
        # Temporarily bypass the date-sequence validation
        # Remove this override once the invoice is confirmed
        return False