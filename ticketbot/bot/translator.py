"""Slash command descriptions and choices in the server's language."""

from discord import app_commands

from ..core.i18n import COMMAND_TEXT

_NOT_TRANSLATED = (
    app_commands.TranslationContextLocation.command_name,
    app_commands.TranslationContextLocation.group_name,
    app_commands.TranslationContextLocation.parameter_name,
)


class CommandTranslator(app_commands.Translator):
    """Translates descriptions and choice names; command names stay in English."""

    async def translate(self, string: app_commands.locale_str, locale, context):
        if context.location in _NOT_TRANSLATED:
            return None
        lang = str(locale.value if hasattr(locale, "value") else locale).split("-")[0]
        return COMMAND_TEXT.get(lang, {}).get(string.message)
