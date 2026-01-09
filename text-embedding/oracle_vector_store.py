import os
import tempfile
import zipfile
from pathlib import Path

from lfx.base.vectorstores.model import LCVectorStoreComponent, check_cached_vector_store
from lfx.helpers.data import docs_to_data
from lfx.io import (
    DropdownInput,
    FileInput,
    FloatInput,
    HandleInput,
    IntInput,
    SecretStrInput,
    StrInput,
)
from lfx.schema.data import Data
from lfx.base.data.storage_utils import parse_storage_path, read_file_bytes
from lfx.services.deps import get_settings_service, get_storage_service
from lfx.utils.async_helpers import run_until_complete


class OracleDatabaseVectorStoreComponent(LCVectorStoreComponent):
    """Oracle Database 23ai vector store with search capabilities."""

    display_name: str = "Oracle Database Vector Store"
    description: str = "Oracle 23ai Vector Store with local embeddings and configurable retrieval"
    name = "OracleDBVector"
    icon = "Oracle"

    inputs = [
        StrInput(
            name="db_user",
            display_name="Database User",
            info="Oracle database username (e.g., ADMIN)",
        ),
        SecretStrInput(
            name="db_password",
            display_name="Database Password",
            info="Oracle database password",
        ),
        StrInput(
            name="dsn",
            display_name="DSN",
            info="Database connection string (e.g., CA4X9LQR5QLMO4EB_high)",
        ),
        FileInput(
            name="wallet_file",
            display_name="Wallet ZIP File",
            info="Upload Oracle wallet ZIP file",
            file_types=["zip"],
        ),
        SecretStrInput(
            name="wallet_password",
            display_name="Wallet Password",
            info="Oracle wallet password",
        ),
        StrInput(
            name="table_name",
            display_name="Table Name",
            info="Vector table name (e.g., PDFCOLLECTION)",
            value="PDFCOLLECTION",
        ),
        IntInput(
            name="embedding_dimension",
            display_name="Embedding Dimension",
            info="Embedding vector dimension (e.g., 1024 for Cohere multilingual v3, 1536 for OpenAI, 768 for Titan)",
            value=1024,
            advanced=True,
        ),
        DropdownInput(
            name="distance_strategy",
            display_name="Distance Strategy",
            options=["COSINE", "EUCLIDEAN_DISTANCE", "DOT_PRODUCT"],
            value="COSINE",
            advanced=True,
        ),
        *LCVectorStoreComponent.inputs,
        HandleInput(
            name="embedding",
            display_name="Embedding Model",
            input_types=["Embeddings"],
        ),
        IntInput(
            name="number_of_results",
            display_name="Number of Results",
            value=5,
            advanced=True,
        ),
        DropdownInput(
            name="search_type",
            display_name="Search Type",
            options=["similarity", "mmr", "similarity_score_threshold"],
            value="similarity",
            advanced=True,
        ),
        FloatInput(
            name="score_threshold",
            display_name="Score Threshold",
            value=0.35,
            advanced=True,
        ),
        IntInput(
            name="fetch_k",
            display_name="Fetch K",
            value=20,
            advanced=True,
        ),
        FloatInput(
            name="mmr_lambda",
            display_name="MMR Lambda",
            value=0.5,
            advanced=True,
        ),
    ]

    def _clean_metadata(self, metadata):
        """Clean metadata to ensure JSON serializability."""
        import json

        if not metadata:
            return {}

        cleaned = {}
        for key, value in metadata.items():
            try:
                json.dumps(value)
                cleaned[key] = value
            except (TypeError, ValueError):
                cleaned[key] = str(value)

        return cleaned

    def _get_wallet_file_path(self) -> str:
        """업로드된 wallet 파일의 로컬 경로를 가져옵니다. S3 storage인 경우 임시 파일로 다운로드합니다."""
        if not self.wallet_file:
            raise ValueError("Wallet file is required")
        
        settings = get_settings_service().settings
        
        # Local storage: 파일 경로를 그대로 사용
        if settings.storage_type == "local":
            if not os.path.exists(self.wallet_file):
                raise FileNotFoundError(f"Wallet file not found: {self.wallet_file}")
            return self.wallet_file
        
        # S3 storage: 파일을 임시 위치로 다운로드
        parsed = parse_storage_path(self.wallet_file)
        if not parsed:
            raise ValueError(f"Invalid S3 path format: {self.wallet_file}. Expected 'flow_id/filename'")
        
        storage_service = get_storage_service()
        flow_id, filename = parsed
        
        # S3에서 파일 내용 가져오기
        content = run_until_complete(storage_service.get_file(flow_id, filename))
        
        # 임시 파일로 저장
        suffix = Path(filename).suffix
        temp_file = tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False)
        try:
            temp_file.write(content)
            temp_file.flush()
            temp_path = temp_file.name
        finally:
            temp_file.close()
        
        self.log(f"Downloaded wallet file from S3 to: {temp_path}")
        return temp_path

    @check_cached_vector_store
    def build_vector_store(self):
        try:
            import oracledb
            from langchain_community.vectorstores.oraclevs import OracleVS
            from langchain_community.vectorstores.utils import DistanceStrategy
        except ImportError as e:
            msg = "Could not import required packages."
            raise ImportError(msg) from e

        # wallet zip 파일 경로 가져오기 (로컬 또는 S3에서 다운로드)
        wallet_file_path = None
        temp_wallet_dir = None
        temp_downloaded_wallet = None
        
        try:
            wallet_file_path = self._get_wallet_file_path()
            
            # S3에서 다운로드한 경우 나중에 정리할 수 있도록 추적
            settings = get_settings_service().settings
            if settings.storage_type == "s3":
                temp_downloaded_wallet = wallet_file_path
            
            # 임시 디렉토리 생성 및 zip 파일 압축 해제
            temp_wallet_dir = tempfile.mkdtemp(prefix="oracle_wallet_")
            self.log(f"Extracting wallet to temporary directory: {temp_wallet_dir}")
            
            with zipfile.ZipFile(wallet_file_path, 'r') as zip_ref:
                zip_ref.extractall(temp_wallet_dir)
            
            self.log(f"Wallet extracted successfully")
            
        except Exception as e:
            # 실패 시 임시 파일들 정리
            if temp_wallet_dir and os.path.exists(temp_wallet_dir):
                import shutil
                shutil.rmtree(temp_wallet_dir, ignore_errors=True)
            if temp_downloaded_wallet and os.path.exists(temp_downloaded_wallet):
                os.unlink(temp_downloaded_wallet)
            error_msg = f"Failed to extract wallet file: {str(e)}"
            self.status = error_msg
            raise RuntimeError(error_msg) from e
        finally:
            # S3에서 다운로드한 임시 wallet 파일 정리
            if temp_downloaded_wallet and os.path.exists(temp_downloaded_wallet):
                try:
                    os.unlink(temp_downloaded_wallet)
                except Exception:
                    pass

        connect_args = {
            "user": self.db_user,
            "password": self.db_password,
            "dsn": self.dsn,
            "config_dir": temp_wallet_dir,
            "wallet_location": temp_wallet_dir,
            "wallet_password": self.wallet_password,
        }

        try:
            conn = oracledb.connect(**connect_args)
            self.log(f"Connected to Oracle Database: {self.dsn}")
        except Exception as e:
            # 연결 실패 시 임시 디렉토리 정리
            if temp_wallet_dir and os.path.exists(temp_wallet_dir):
                import shutil
                shutil.rmtree(temp_wallet_dir, ignore_errors=True)
            error_msg = f"Failed to connect to Oracle Database: {str(e)}"
            self.status = error_msg
            raise ConnectionError(error_msg) from e

        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT table_name FROM user_tables WHERE UPPER(table_name) = UPPER(:table_name)",
                {"table_name": self.table_name},
            )
            row = cursor.fetchone()

            if not row:
                # 테이블이 존재하지 않으면 생성
                self.log(f"Table '{self.table_name}' does not exist. Creating table...")
                try:
                    # Embedding dimension 설정 (기본값: 1024)
                    embed_dim = getattr(self, 'embedding_dimension', 1024)
                    self.log(f"Using embedding dimension: {embed_dim}")

                    # 테이블 생성 SQL
                    create_table_sql = f"""
                    CREATE TABLE {self.db_user}.{self.table_name} (
                        ID VARCHAR2(100 BYTE),
                        TEXT CLOB,
                        METADATA CLOB,
                        EMBEDDING VECTOR({embed_dim}, *),
                        CREATED_AT TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                    cursor.execute(create_table_sql)
                    self.log(f"Table '{self.table_name}' created successfully with dimension {embed_dim}")
                    
                    # Primary Key 추가
                    pk_sql = f"""
                    ALTER TABLE {self.db_user}.{self.table_name} ADD PRIMARY KEY (ID)
                    USING INDEX PCTFREE 10 INITRANS 20 MAXTRANS 255
                    TABLESPACE DATA ENABLE
                    """
                    cursor.execute(pk_sql)
                    self.log(f"Primary key added to '{self.table_name}'")
                    
                    # Vector 인덱스 생성
                    index_sql = f"""
                    CREATE VECTOR INDEX {self.db_user}.VECTOR_IDX_{self.table_name} ON {self.db_user}.{self.table_name} (EMBEDDING)
                    ORGANIZATION INMEMORY NEIGHBOR GRAPH
                    WITH DISTANCE COSINE
                    WITH TARGET ACCURACY 95
                    """
                    cursor.execute(index_sql)
                    self.log(f"Vector index created for '{self.table_name}'")
                    
                    conn.commit()
                    actual_table_name = self.table_name
                except Exception as create_error:
                    conn.rollback()
                    cursor.close()
                    error_msg = f"Failed to create table '{self.table_name}': {str(create_error)}"
                    self.status = error_msg
                    raise RuntimeError(error_msg) from create_error
            else:
                actual_table_name = row[0]
                self.log(f"Found existing table: {actual_table_name}")
            
            cursor.close()
        except Exception as e:
            error_msg = f"Failed to validate or create table: {str(e)}"
            self.status = error_msg
            raise RuntimeError(error_msg) from e

        ds_map = {
            "COSINE": DistanceStrategy.COSINE,
            "EUCLIDEAN_DISTANCE": DistanceStrategy.EUCLIDEAN_DISTANCE,
            "DOT_PRODUCT": DistanceStrategy.DOT_PRODUCT,
        }
        distance = ds_map.get(self.distance_strategy, DistanceStrategy.COSINE)

        # Embedding 모델 검증 (OracleVS 초기화 전에 테스트)
        try:
            self.log("Validating embedding model...")
            test_embedding = self.embedding.embed_query("test")
            actual_dim = len(test_embedding)
            expected_dim = getattr(self, 'embedding_dimension', 1024)

            if actual_dim != expected_dim:
                warning_msg = f"Warning: Embedding dimension mismatch. Expected: {expected_dim}, Got: {actual_dim}"
                self.log(warning_msg)
                # 실제 차원으로 업데이트
                self.embedding_dimension = actual_dim

            self.log(f"Embedding model validated. Dimension: {actual_dim}")
        except Exception as e:
            error_msg = f"Failed to validate embedding model. Please check your embedding model configuration: {str(e)}"
            self.status = error_msg
            self.log(error_msg)
            raise RuntimeError(error_msg) from e

        try:
            oracle_store = OracleVS(
                client=conn,
                table_name=actual_table_name,
                distance_strategy=distance,
                embedding_function=self.embedding,
            )
            self.log(f"Created OracleVS instance for table: {actual_table_name}")
        except Exception as e:
            error_msg = f"Failed to create OracleVS instance: {str(e)}"
            self.status = error_msg
            self.log(error_msg)
            raise RuntimeError(error_msg) from e

        self.ingest_data = self._prepare_ingest_data()

        documents = []
        for _input in self.ingest_data or []:
            if isinstance(_input, Data):
                doc = _input.to_lc_document()
                doc.metadata = self._clean_metadata(doc.metadata)
                documents.append(doc)
            else:
                if hasattr(_input, 'metadata'):
                    _input.metadata = self._clean_metadata(_input.metadata)
                documents.append(_input)

        if documents:
            try:
                self.log(f"Ingesting {len(documents)} documents...")
                oracle_store.add_documents(documents)
                success_msg = f"Successfully added {len(documents)} documents"
                self.status = success_msg
                self.log(success_msg)
            except Exception as e:
                error_msg = f"Failed to add documents: {str(e)}"
                self.status = error_msg
                self.log(error_msg)
                raise RuntimeError(error_msg) from e

        return oracle_store

    def search_documents(self) -> list[Data]:
        vector_store = self.build_vector_store()

        if self.search_query and isinstance(self.search_query, str) and self.search_query.strip():
            query = self.search_query.strip()
            k = max(1, self.number_of_results or 5)

            self.log(f"Searching for: {query}")

            try:
                if self.search_type == "similarity":
                    kwargs = {}
                    if self.fetch_k:
                        kwargs["fetch_k"] = self.fetch_k
                    docs = vector_store.similarity_search(query=query, k=k, **kwargs)

                elif self.search_type == "mmr":
                    kwargs = {}
                    if self.fetch_k:
                        kwargs["fetch_k"] = self.fetch_k
                    docs = vector_store.max_marginal_relevance_search(
                        query=query,
                        k=k,
                        lambda_mult=self.mmr_lambda,
                        **kwargs,
                    )

                elif self.search_type == "similarity_score_threshold":
                    retriever = vector_store.as_retriever(
                        search_type="similarity_score_threshold",
                        search_kwargs={
                            "k": k,
                            "score_threshold": self.score_threshold,
                            **({"fetch_k": self.fetch_k} if self.fetch_k else {}),
                        },
                    )
                    docs = retriever.get_relevant_documents(query)

                else:
                    docs = vector_store.similarity_search(query=query, k=k)

                data = docs_to_data(docs)
                self.status = data
                self.log(f"Found {len(docs)} results")
                return data

            except Exception as e:
                error_msg = f"Search failed: {str(e)}"
                self.status = error_msg
                self.log(error_msg)
                return []

        return []