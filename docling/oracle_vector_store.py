import os
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

from typing_extensions import override

from lfx.base.vectorstores.model import LCVectorStoreComponent, check_cached_vector_store
from lfx.base.data.storage_utils import parse_storage_path
from lfx.services.deps import get_settings_service, get_storage_service
from lfx.utils.async_helpers import run_until_complete
from lfx.inputs.inputs import BoolInput, DropdownInput, HandleInput, IntInput, SecretStrInput, StrInput
from lfx.io import FileInput
from lfx.schema.data import Data

if TYPE_CHECKING:
    from langchain_community.vectorstores.oraclevs import OracleVS
    from lfx.schema.dataframe import DataFrame


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
        *LCVectorStoreComponent.inputs,
        HandleInput(
            name="embedding",
            display_name="Embedding Model",
            input_types=["Embeddings"],
        ),
        DropdownInput(
            name="distance_strategy",
            display_name="Distance Strategy",
            options=["COSINE", "EUCLIDEAN_DISTANCE", "DOT_PRODUCT"],
            value="COSINE",
            advanced=True,
        ),
        BoolInput(
            name="allow_duplicates",
            display_name="Allow Duplicates",
            advanced=True,
            value=False,
            info="If false, will not add documents that are already in the Vector Store.",
        ),
        DropdownInput(
            name="search_type",
            display_name="Search Type",
            options=["Similarity", "MMR"],
            value="Similarity",
            advanced=True,
        ),
        IntInput(
            name="number_of_results",
            display_name="Number of Results",
            info="Number of results to return.",
            advanced=True,
            value=10,
        ),
        IntInput(
            name="limit",
            display_name="Limit",
            advanced=True,
            info="Limit the number of records to compare when Allow Duplicates is False.",
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

    def _oracle_table_to_data(self, conn, table_name: str, limit: int | None = None) -> list[Data]:
        """Oracle 테이블에서 데이터를 가져와 Data 객체 리스트로 변환합니다 (ChromaDB의 chroma_collection_to_data와 유사)."""
        try:
            cursor = conn.cursor()
            
            # Limit 적용하여 쿼리 실행
            if limit:
                query = f"SELECT ID, TEXT, METADATA FROM {table_name} WHERE ROWNUM <= :limit"
                cursor.execute(query, {"limit": limit})
            else:
                query = f"SELECT ID, TEXT, METADATA FROM {table_name}"
                cursor.execute(query)
            
            rows = cursor.fetchall()
            cursor.close()
            
            data_list = []
            for row in rows:
                doc_id, text, metadata_json = row
                
                # metadata JSON 파싱
                metadata = {}
                if metadata_json:
                    import json
                    try:
                        metadata = json.loads(metadata_json)
                    except json.JSONDecodeError:
                        metadata = {}
                
                data = Data(
                    id=doc_id,
                    text=text,
                    data=metadata,
                )
                data_list.append(data)
            
            return data_list
            
        except Exception as e:
            self.log(f"Failed to fetch data from Oracle table: {str(e)}")
            return []

    @override
    @check_cached_vector_store
    def build_vector_store(self) -> "OracleVS":
        """Builds the Oracle Vector Store object."""
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
            
            # S3에서 다운로드한 경우 나중에
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
                    # 테이블 생성 SQL
                    create_table_sql = f"""
                    CREATE TABLE {self.db_user}.{self.table_name} (
                        ID VARCHAR2(100 BYTE),
                        TEXT CLOB,
                        METADATA CLOB,
                        EMBEDDING VECTOR(1024, *),
                        CREATED_AT TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                    cursor.execute(create_table_sql)
                    self.log(f"Table '{self.table_name}' created successfully")
                    
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

        oracle_store = OracleVS(
            client=conn,
            table_name=actual_table_name,
            distance_strategy=distance,
            embedding_function=self.embedding,
        )

        self.log(f"Created OracleVS instance for table: {actual_table_name}")

        # ChromaDB 스타일: 문서 추가를 별도 메서드로 분리
        self._add_documents_to_vector_store(oracle_store, conn, actual_table_name)
        
        # ChromaDB 스타일: 상태 업데이트
        limit = int(self.limit) if self.limit is not None and str(self.limit).strip() else None
        self.status = self._oracle_table_to_data(conn, actual_table_name, limit=limit)
        
        return oracle_store

    def _add_documents_to_vector_store(self, vector_store: "OracleVS", conn, table_name: str) -> None:
        """Adds documents to the Vector Store (ChromaDB 스타일)."""
        ingest_data: list | Data | "DataFrame" = self.ingest_data
        if not ingest_data:
            self.status = ""
            return

        # Convert DataFrame to Data if needed using parent's method
        ingest_data = self._prepare_ingest_data()

        stored_documents_without_id = []
        if self.allow_duplicates:
            stored_data = []
        else:
            limit = int(self.limit) if self.limit is not None and str(self.limit).strip() else None
            stored_data = self._oracle_table_to_data(conn, table_name, limit=limit)
            for value in deepcopy(stored_data):
                # ID 제거하여 텍스트/메타데이터만으로 비교 (ChromaDB와 동일한 방식)
                del value.id
                stored_documents_without_id.append(value)

        documents = []
        for _input in ingest_data or []:
            if isinstance(_input, Data):
                # ChromaDB 스타일: 중복 체크
                if _input not in stored_documents_without_id:
                    doc = _input.to_lc_document()
                    doc.metadata = self._clean_metadata(doc.metadata)
                    documents.append(doc)
            else:
                msg = "Vector Store Inputs must be Data objects."
                raise TypeError(msg)

        if documents and self.embedding is not None:
            self.log(f"Adding {len(documents)} documents to the Vector Store.")
            try:
                vector_store.add_documents(documents)
            except Exception as e:
                self.log(f"Warning: Failed to add documents: {str(e)}")
                raise
        else:
            self.log("No documents to add to the Vector Store.")