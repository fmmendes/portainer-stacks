```sql
CREATE DATABASE airflow3_db;
CREATE USER airflow3_user WITH PASSWORD 'airflow_pass';
GRANT ALL PRIVILEGES ON DATABASE airflow3_db TO airflow3_user;

-- PostgreSQL 15 requires additional privileges:
-- Note: Connect to the airflow3_db database before running the following GRANT statement
-- You can do this in psql with: \c airflow3_db
GRANT ALL ON SCHEMA public TO airflow3_user;
```
