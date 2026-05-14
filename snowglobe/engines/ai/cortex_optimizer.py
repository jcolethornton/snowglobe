class CortexOptimizer:

    def __init__(self, connection):
        self.connection = connection

    def analyze_query(self, sql_text, suggestions, cost_attributes):

        prompt = f"""
        You are a Snowflake performance expert.
        Analyze the following SQL query, suggestions and cost attributes.
        Provide snipplets of optimized SQL based on the suggestions and cost attributes, along with explanations for each optimization.

        SQL:
        {sql_text}

        Suggestions:
        {suggestions}

        Cost Attributes:
        {cost_attributes}
        """

        with self.connection:

            sql = f"""
            SELECT 
                REPLACE(
                    AI_COMPLETE(
                        model => 'claude-haiku-4-5',
                        prompt => $$ {prompt} $$
                        response_format => {
                        'type': 'json',
                        'schema': {
                            'summary': 'string',
                            'optimizations': [
                                'problem': 'string',
                                'solution': 'string',
                                'sql': 'string',
                                'explanation': 'string'
                            ],
                            'expected_improvement': 'string'
                        }
            },
            'required': ['category']
            }
        }
                    ),
                '\\n',
                '\n'
                ) as AI_RESULT
            """
            result = self.connection.query(sql)

        return result[0]["AI_RESULT"] if result else "No AI suggestions"
