-- A executer avec un compte administrateur PostgreSQL :  psql -U postgres -h localhost -f scripts/creer_base.sql
-- Cree le role et la base SEULEMENT s'ils n'existent pas. Changez le mot de passe avant d'executer.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'artec') THEN
    CREATE ROLE artec LOGIN PASSWORD 'CHANGEZ-MOI' CREATEDB;   -- CREATEDB : requis par "manage.py test"
  END IF;
END $$;
SELECT 'CREATE DATABASE artec OWNER artec' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'artec') \gexec
