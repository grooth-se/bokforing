"""
Backup-tjänst - Säkerhetskopiering till lokalt nätverk

Funktioner:
- Schemalagd backup av databas och dokument
- Retry vid nätverksfel
- Inkrementell backup av dokument
- Återställning från backup
"""
import os
import shutil
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List
import threading
import time
import socket


class BackupService:
    """
    Tjänst för säkerhetskopiering

    Backup inkluderar:
    - SQLite-databas
    - Uppladdade dokument (från databasen)
    - Konfiguration

    Backup-struktur på nätverket:
    /backup_path/
        /YYYY-MM-DD_HHMMSS/
            bokforing.db
            /documents/
                company_1/
                    doc_1.pdf
                    ...
            manifest.json
    """

    def __init__(
        self,
        db_path: str,
        backup_base_path: str,
        retention_days: int = 30
    ):
        self.db_path = Path(db_path)
        self.backup_base_path = Path(backup_base_path)
        self.retention_days = retention_days
        self._pending_backup = False
        self._backup_thread = None
        self._stop_flag = False

    def is_network_available(self) -> bool:
        """Kontrollera om backup-platsen är tillgänglig"""
        try:
            # Försök skapa/komma åt backup-mappen
            self.backup_base_path.mkdir(parents=True, exist_ok=True)
            test_file = self.backup_base_path / ".backup_test"
            test_file.touch()
            test_file.unlink()
            return True
        except (OSError, PermissionError):
            return False

    def get_backup_folder_name(self) -> str:
        """Generera backup-mappnamn med tidsstämpel"""
        return datetime.now().strftime("%Y-%m-%d_%H%M%S")

    def create_backup(self, db_session=None) -> Dict:
        """
        Skapa komplett backup

        Returns:
            Dict med backup-information
        """
        if not self.is_network_available():
            self._pending_backup = True
            return {
                'success': False,
                'error': 'Nätverksplatsen är inte tillgänglig',
                'pending': True
            }

        backup_name = self.get_backup_folder_name()
        backup_path = self.backup_base_path / backup_name

        try:
            backup_path.mkdir(parents=True, exist_ok=True)

            # Kopiera databas
            db_backup_path = backup_path / "bokforing.db"
            shutil.copy2(self.db_path, db_backup_path)

            # Exportera dokument om db_session finns
            docs_exported = 0
            if db_session:
                docs_exported = self._export_documents(db_session, backup_path / "documents")

            # Skapa manifest
            manifest = {
                'created_at': datetime.now().isoformat(),
                'db_size': db_backup_path.stat().st_size,
                'db_hash': self._file_hash(db_backup_path),
                'documents_count': docs_exported,
                'source_host': socket.gethostname(),
            }

            manifest_path = backup_path / "manifest.json"
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            self._pending_backup = False

            # Rensa gamla backups
            self._cleanup_old_backups()

            return {
                'success': True,
                'backup_path': str(backup_path),
                'backup_name': backup_name,
                'manifest': manifest
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'pending': False
            }

    def _export_documents(self, db_session, docs_path: Path) -> int:
        """Exportera alla dokument från databasen"""
        from app.models import CompanyDocument, Company

        docs_path.mkdir(parents=True, exist_ok=True)
        count = 0

        documents = db_session.query(CompanyDocument).all()

        for doc in documents:
            company = db_session.query(Company).filter(Company.id == doc.company_id).first()
            company_folder = docs_path / f"company_{doc.company_id}"
            if company:
                company_folder = docs_path / self._safe_filename(company.name)

            company_folder.mkdir(parents=True, exist_ok=True)

            # Filnamn med version och typ
            safe_name = self._safe_filename(doc.name)
            filename = f"{doc.document_type.value}_v{doc.version}_{safe_name}_{doc.filename}"
            file_path = company_folder / filename

            with open(file_path, 'wb') as f:
                f.write(doc.file_data)

            count += 1

        return count

    def _safe_filename(self, name: str) -> str:
        """Skapa säkert filnamn"""
        return "".join(c if c.isalnum() or c in ' -_' else '_' for c in name).strip()

    def _file_hash(self, file_path: Path) -> str:
        """Beräkna SHA256 hash för fil"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _cleanup_old_backups(self):
        """Ta bort backups äldre än retention_days"""
        if not self.backup_base_path.exists():
            return

        cutoff_date = datetime.now() - timedelta(days=self.retention_days)

        for item in self.backup_base_path.iterdir():
            if item.is_dir():
                try:
                    # Parse datum från mappnamn (YYYY-MM-DD_HHMMSS)
                    folder_date = datetime.strptime(item.name[:10], "%Y-%m-%d")
                    if folder_date < cutoff_date:
                        shutil.rmtree(item)
                except (ValueError, OSError):
                    pass  # Ignorera mappar som inte matchar formatet

    def list_backups(self) -> List[Dict]:
        """Lista tillgängliga backups"""
        backups = []

        if not self.backup_base_path.exists():
            return backups

        for item in sorted(self.backup_base_path.iterdir(), reverse=True):
            if item.is_dir():
                manifest_path = item / "manifest.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path, 'r', encoding='utf-8') as f:
                            manifest = json.load(f)
                        backups.append({
                            'name': item.name,
                            'path': str(item),
                            'created_at': manifest.get('created_at'),
                            'db_size': manifest.get('db_size'),
                            'documents_count': manifest.get('documents_count', 0)
                        })
                    except (json.JSONDecodeError, OSError):
                        pass

        return backups

    def restore_backup(self, backup_name: str) -> Dict:
        """
        Återställ från backup

        OBS: Stoppar inte appen - detta bör göras separat
        """
        backup_path = self.backup_base_path / backup_name

        if not backup_path.exists():
            return {'success': False, 'error': 'Backup finns inte'}

        db_backup = backup_path / "bokforing.db"
        if not db_backup.exists():
            return {'success': False, 'error': 'Databasfil saknas i backup'}

        try:
            # Skapa backup av nuvarande databas först
            current_backup = self.db_path.with_suffix('.db.bak')
            shutil.copy2(self.db_path, current_backup)

            # Kopiera backup-databasen
            shutil.copy2(db_backup, self.db_path)

            return {
                'success': True,
                'restored_from': backup_name,
                'previous_backup': str(current_backup)
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def start_background_sync(self, interval_minutes: int = 60):
        """Starta bakgrundssynkronisering"""
        self._stop_flag = False

        def sync_loop():
            while not self._stop_flag:
                if self._pending_backup or self._should_backup():
                    from app.models import SessionLocal
                    db = SessionLocal()
                    try:
                        self.create_backup(db)
                    finally:
                        db.close()

                # Sov i intervallet, men kolla stop_flag varje minut
                for _ in range(interval_minutes):
                    if self._stop_flag:
                        break
                    time.sleep(60)

        self._backup_thread = threading.Thread(target=sync_loop, daemon=True)
        self._backup_thread.start()

    def stop_background_sync(self):
        """Stoppa bakgrundssynkronisering"""
        self._stop_flag = True
        if self._backup_thread:
            self._backup_thread.join(timeout=5)

    def _should_backup(self) -> bool:
        """Kontrollera om det är dags för backup"""
        backups = self.list_backups()
        if not backups:
            return True

        # Backup om senaste är äldre än 24 timmar
        try:
            latest = datetime.fromisoformat(backups[0]['created_at'])
            return (datetime.now() - latest) > timedelta(hours=24)
        except (ValueError, KeyError):
            return True


class BackupConfig:
    """Konfiguration för backup"""

    CONFIG_FILE = "backup_config.json"

    def __init__(self, config_dir: str = "data"):
        self.config_path = Path(config_dir) / self.CONFIG_FILE
        self._config = self._load()

    def _load(self) -> Dict:
        """Ladda konfiguration"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        return {
            'backup_path': '',
            'enabled': False,
            'interval_hours': 24,
            'retention_days': 30,
            'last_backup': None
        }

    def save(self):
        """Spara konfiguration"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    @property
    def backup_path(self) -> str:
        return self._config.get('backup_path', '')

    @backup_path.setter
    def backup_path(self, value: str):
        self._config['backup_path'] = value
        self.save()

    @property
    def enabled(self) -> bool:
        return self._config.get('enabled', False)

    @enabled.setter
    def enabled(self, value: bool):
        self._config['enabled'] = value
        self.save()

    @property
    def interval_hours(self) -> int:
        return self._config.get('interval_hours', 24)

    @interval_hours.setter
    def interval_hours(self, value: int):
        self._config['interval_hours'] = value
        self.save()

    @property
    def retention_days(self) -> int:
        return self._config.get('retention_days', 30)

    @retention_days.setter
    def retention_days(self, value: int):
        self._config['retention_days'] = value
        self.save()

    @property
    def last_backup(self) -> Optional[str]:
        return self._config.get('last_backup')

    @last_backup.setter
    def last_backup(self, value: str):
        self._config['last_backup'] = value
        self.save()
