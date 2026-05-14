from prompt_toolkit.completion import Completer, Completion


class SnowglobeCompleter(Completer):
    def __init__(self, ctx):
        self.ctx = ctx

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        word = document.get_word_before_cursor()
        start_position = -len(word)

        parts = text.strip().split()

        # Are we starting a new word?
        new_word = text.endswith(" ")

        # No command yet
        if not parts:
            for cmd in ["use", "inspect", "refresh", "set"]:
                yield Completion(cmd, start_position=start_position)
            return

        command = parts[0]

        # Completing command name
        if len(parts) == 1 and not new_word:
            for cmd in ["use", "inspect", "refresh", "set"]:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=start_position)
            return

        # ---- use command ----
        if command == "use":

            # Completing second token (user/role)
            if len(parts) == 1 and new_word:
                for option in ["user", "role"]:
                    yield Completion(option, start_position=0)
                return

            if len(parts) == 2 and not new_word:
                for option in ["user", "role"]:
                    if option.startswith(word):
                        yield Completion(option, start_position=start_position)
                return

            # Completing third token (name)
            if len(parts) == 2 and new_word:
                kind = parts[1]

                if kind == "role" and self.ctx.role_graph:
                    for role in self.ctx.role_graph.roles.keys():
                        yield Completion(role, start_position=0)

                elif kind == "user" and self.ctx.user_graph:
                    for user in self.ctx.user_graph.assigned_roles.keys():
                        yield Completion(user, start_position=0)

                return

            if len(parts) == 3 and not new_word:
                kind = parts[1]

                if kind == "role" and self.ctx.role_graph:
                    for role in self.ctx.role_graph.roles.keys():
                        if role.startswith(word):
                            yield Completion(role, start_position=start_position)

                elif kind == "user" and self.ctx.user_graph:
                    for user in self.ctx.user_graph.assigned_roles.keys():
                        if user.startswith(word):
                            yield Completion(user, start_position=start_position)

                return
