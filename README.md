# ❄️ Snow Globe

A lightweight CLI tool for providing visibility on Snowflake ACL, infrastructure, and costs.

---

## Features

- Export infrastructure with a single command
- Trace object lineage across databases and schemas

---

## 📦 Installation

### Using pip
```bash
pip install snowglobe
```

### From source
Clone the repository and install:

```bash
git clone https://github.com/jcolethornton/snowglobe.git
cd snowglobe
pip install .
```

## Requirements
- Python 3.11+
- A Snowflake account
- Snowflake credentials set as environment variables or in a config file


## Configuration
By default, Snowglobe uses Snowflake credentials from environment variables:

Variable	Example
SNOWFLAKE_USER	jdoe
SNOWFLAKE_PASSWORD	supersecret
SNOWFLAKE_ACCOUNT	xy12345.region.aws
SNOWFLAKE_WAREHOUSE	COMPUTE_WH
SNOWFLAKE_ROLE	SYSADMIN


## Contributing
Pull requests and issues are welcome!

## License
MIT © 2025 Jaryd Thornton
