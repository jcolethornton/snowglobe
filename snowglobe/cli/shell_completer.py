from prompt_toolkit.completion import Completer, Completion

SHELL_COMMANDS = ["check", "roles", "members", "path", "escalation", "scan", "use", "set", "access", "whoaccess", "create", "cost", "optimize", "refresh", "status", "debug", "help", "exit", "?"]
SET_FIELDS = ["object_type", "object_name", "privilege"]


class SnowglobeCompleter(Completer):
    def __init__(self, ctx):
        self.ctx = ctx

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        word = document.get_word_before_cursor()
        start_position = -len(word)

        parts = text.strip().split()
        new_word = text.endswith(" ")

        # No input yet — suggest all commands
        if not parts:
            for cmd in SHELL_COMMANDS:
                yield Completion(cmd, start_position=start_position)
            return

        command = parts[0]

        # Completing command name (first word, still typing)
        if len(parts) == 1 and not new_word:
            for cmd in SHELL_COMMANDS:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=start_position)
            return

        # ---- roles command (expects a username) ----
        if command == "roles":
            if (len(parts) == 1 and new_word) or (len(parts) == 2 and not new_word):
                yield from self._complete_users(start_position, word if not new_word else None)
                return

        # ---- members command (expects a role) ----
        if command == "members":
            if (len(parts) == 1 and new_word) or (len(parts) == 2 and not new_word):
                yield from self._complete_roles(start_position, word if not new_word else None)
                return

        # ---- path command (expects from_role, then to_role) ----
        if command == "path":
            if (len(parts) == 1 and new_word) or (len(parts) == 2 and not new_word):
                yield from self._complete_roles(start_position, word if not new_word else None)
                return
            if (len(parts) == 2 and new_word) or (len(parts) == 3 and not new_word):
                yield from self._complete_roles(start_position, word if not new_word else None)
                return

        # ---- escalation command (expects a role) ----
        if command == "escalation":
            if (len(parts) == 1 and new_word) or (len(parts) == 2 and not new_word):
                yield from self._complete_roles(start_position, word if not new_word else None)
                return

        # ---- use command ----
        if command == "use":
            if len(parts) == 1 and new_word:
                for option in ["user", "role"]:
                    yield Completion(option, start_position=0)
                return

            if len(parts) == 2 and not new_word:
                for option in ["user", "role"]:
                    if option.startswith(word):
                        yield Completion(option, start_position=start_position)
                return

            # Completing the name (third token)
            if len(parts) == 2 and new_word:
                kind = parts[1]
                if kind == "role":
                    yield from self._complete_roles(0, None)
                elif kind == "user":
                    yield from self._complete_users(0, None)
                return

            if len(parts) == 3 and not new_word:
                kind = parts[1]
                if kind == "role":
                    yield from self._complete_roles(start_position, word)
                elif kind == "user":
                    yield from self._complete_users(start_position, word)
                return

        # ---- set command ----
        if command == "set":
            if len(parts) == 1 and new_word:
                for field in SET_FIELDS:
                    yield Completion(field, start_position=0)
                return

            if len(parts) == 2 and not new_word:
                for field in SET_FIELDS:
                    if field.startswith(word):
                        yield Completion(field, start_position=start_position)
                return

    def _complete_roles(self, start_position, prefix=None):
        """Yield role name completions."""
        if not self.ctx.role_graph:
            return
        for role in self.ctx.role_graph.roles.keys():
            if prefix is None or role.upper().startswith(prefix.upper()):
                yield Completion(role, start_position=start_position)

    def _complete_users(self, start_position, prefix=None):
        """Yield user name completions."""
        if not self.ctx.user_graph:
            return
        for user in self.ctx.user_graph.assigned_roles.keys():
            if prefix is None or user.upper().startswith(prefix.upper()):
                yield Completion(user, start_position=start_position)
