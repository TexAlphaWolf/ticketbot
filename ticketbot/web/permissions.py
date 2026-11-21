"""Who may see what in the dashboard: the same rules as the bot on Discord.

- Admin of a server (owner or Administrator permission): everything.
- Staff: the tickets they could handle on Discord. The staff role covers the types that
  have no roles of their own; a type's roles cover that type; the role of an escalation
  level covers the tickets escalated to that level or higher.
"""

from dataclasses import dataclass

from ..db.store import TicketScope

ADMINISTRATOR = 1 << 3


@dataclass(frozen=True)
class Access:
    guild_id: int
    admin: bool
    roles: frozenset[int]
    cfg: dict
    type_roles: dict[str, list[int]]
    levels: list[dict]

    @property
    def staff_role(self) -> bool:
        return self.cfg.get("staff_role") in self.roles

    @property
    def role(self) -> str | None:
        """'admin', 'staff', or None (no access to this server in the dashboard)."""
        if self.admin:
            return "admin"
        if self.staff_role or any(self.roles & set(r) for r in self.type_roles.values()) \
                or any(lv["role_id"] in self.roles for lv in self.levels):
            return "staff"
        return None

    @property
    def can_see_stats(self) -> bool:      # like /stats: admins and the staff role
        return self.admin or self.staff_role

    def scope(self) -> TicketScope | None:
        """For the database query; None = every ticket (admins)."""
        if self.admin:
            return None
        mine = [lv["level"] for lv in self.levels if lv["role_id"] in self.roles]
        return TicketScope(
            types=frozenset(k for k, roles in self.type_roles.items()
                            if self.roles & set(roles)),
            other_types=self.staff_role,
            types_with_roles=frozenset(k for k, roles in self.type_roles.items() if roles),
            min_level=min(mine) if mine else None)

    def can_see(self, ticket: dict) -> bool:
        if self.admin:
            return True
        reached = ticket.get("escalation_level") or 0
        if any(lv["role_id"] in self.roles and lv["level"] <= reached for lv in self.levels):
            return True
        roles = self.type_roles.get(ticket["type_key"])
        return bool(self.roles & set(roles)) if roles else self.staff_role


def is_admin(oauth_guild: dict) -> bool:
    """From an entry of Discord's /users/@me/guilds."""
    return bool(oauth_guild.get("owner")) or \
        bool(int(oauth_guild.get("permissions") or 0) & ADMINISTRATOR)
