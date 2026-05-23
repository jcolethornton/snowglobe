import json


class CortexOptimizer:

    def __init__(self, connection):
        self.connection = connection

    def analyze_query(self, sql_text, suggestions, cost_attributes, model: str = "claude-haiku-4-5"):

        prompt = (
            "You are a Snowflake performance expert. "
            "Analyze the following SQL query, suggestions and cost attributes. "
            "Provide snippets of optimized SQL based on the suggestions and cost attributes, "
            "along with explanations for each optimization. Respond in JSON.\n\n"
            f"SQL:\n{sql_text}\n\n"
            f"Suggestions:\n{suggestions}\n\n"
            f"Cost Attributes:\n{cost_attributes}"
        )

        # Escape single quotes in prompt for SQL embedding
        safe_prompt = prompt.replace("'", "''")

        sql = f"""
        SELECT AI_COMPLETE(
            model => '{model}',
            prompt => '{safe_prompt}',
            response_format => {{
                'type': 'json',
                'schema': {{
                    'type': 'object',
                    'properties': {{
                        'summary': {{'type': 'string'}},
                        'optimizations': {{
                            'type': 'array',
                            'items': {{
                                'type': 'object',
                                'properties': {{
                                    'problem': {{'type': 'string'}},
                                    'solution': {{'type': 'string'}},
                                    'sql': {{'type': 'string'}},
                                    'explanation': {{'type': 'string'}}
                                }},
                                'required': ['problem', 'solution', 'sql', 'explanation']
                            }}
                        }},
                        'expected_improvement': {{'type': 'string'}}
                    }},
                    'required': ['summary', 'optimizations', 'expected_improvement']
                }}
            }}
        ) AS AI_RESULT
        """

        with self.connection:
            result = self.connection.query(sql)

        return result[0]["AI_RESULT"] if result else "No AI suggestions"
