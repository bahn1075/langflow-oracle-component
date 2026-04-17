-- 1. 유저 생성
CREATE ROLE langflow
  WITH LOGIN
  PASSWORD 'YourPasswordHere'
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT;

-- 2. 데이터베이스 생성
CREATE DATABASE langflow
  OWNER langflow
  ENCODING 'UTF8'
  TEMPLATE template0;

-- 3. langflow DB로 접속 전환
\c langflow

-- 4. 스키마 생성
CREATE SCHEMA IF NOT EXISTS langflow AUTHORIZATION langflow;

-- 5. 기본 search_path 설정
ALTER ROLE langflow IN DATABASE langflow
  SET search_path TO langflow, public;

-- 6. 연결 및 스키마 사용 권한
GRANT CONNECT ON DATABASE langflow TO langflow;
GRANT USAGE, CREATE ON SCHEMA langflow TO langflow;

-- 7. public 스키마는 필요 최소화
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO langflow;

-- 8. 혹시 이후 postgres 등 다른 계정이 객체를 만들 경우를 대비한 기본 권한
ALTER DEFAULT PRIVILEGES FOR ROLE langflow IN SCHEMA langflow
  GRANT ALL ON TABLES TO langflow;

ALTER DEFAULT PRIVILEGES FOR ROLE langflow IN SCHEMA langflow
  GRANT ALL ON SEQUENCES TO langflow;

ALTER DEFAULT PRIVILEGES FOR ROLE langflow IN SCHEMA langflow
  GRANT ALL ON FUNCTIONS TO langflow;