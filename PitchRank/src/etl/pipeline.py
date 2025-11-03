"""ETL Pipeline Framework for PitchRank"""
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
import uuid

from supabase import Client
from rich.progress import Progress, SpinnerColumn, TextColumn

logger = logging.getLogger(__name__)

@dataclass
class ETLContext:
    """Context for ETL operations"""
    build_id: str
    provider_id: str
    started_at: datetime
    parameters: Dict
    
class ETLPipeline:
    """Base ETL Pipeline with logging and error handling"""
    
    def __init__(self, supabase: Client, provider_code: str):
        self.db = supabase
        self.provider_code = provider_code
        self.build_id = self._generate_build_id()
        self.errors = []
        self.warnings = []
        
    def _generate_build_id(self) -> str:
        """Generate unique build ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{self.provider_code}_{timestamp}_{uuid.uuid4().hex[:8]}"
        
    def run(self, **kwargs):
        """Run the complete pipeline"""
        context = ETLContext(
            build_id=self.build_id,
            provider_id=self._get_provider_id(),
            started_at=datetime.now(),
            parameters=kwargs
        )
        
        # Log build start
        self._log_build_start('full_pipeline', context)
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True
            ) as progress:
                # Stage 1: Extract
                task = progress.add_task("Extracting data...", total=None)
                data = self.extract(context)
                progress.update(task, completed=True)
                
                # Stage 2: Transform
                task = progress.add_task("Transforming data...", total=None)
                transformed = self.transform(data, context)
                progress.update(task, completed=True)
                
                # Stage 3: Load
                task = progress.add_task("Loading data...", total=None)
                result = self.load(transformed, context)
                progress.update(task, completed=True)
                
            # Log successful completion
            self._log_build_complete('full_pipeline', context, result)
            
            return result
            
        except Exception as e:
            # Log failure
            self._log_build_error('full_pipeline', context, str(e))
            raise
            
    def extract(self, context: ETLContext) -> List[Dict]:
        """Extract stage - to be implemented by subclasses"""
        raise NotImplementedError
        
    def transform(self, data: List[Dict], context: ETLContext) -> List[Dict]:
        """Transform stage - to be implemented by subclasses"""
        raise NotImplementedError
        
    def load(self, data: List[Dict], context: ETLContext) -> Dict:
        """Load stage - to be implemented by subclasses"""
        raise NotImplementedError
        
    def _get_provider_id(self) -> str:
        """Get provider UUID from code"""
        result = self.db.table('providers').select('id').eq('code', self.provider_code).single().execute()
        return result.data['id']
        
    def _log_build_start(self, stage: str, context: ETLContext):
        """Log build start"""
        self.db.table('build_logs').insert({
            'build_id': context.build_id,
            'stage': stage,
            'provider_id': context.provider_id,
            'parameters': context.parameters
        }).execute()
        
    def _log_build_complete(self, stage: str, context: ETLContext, result: Dict):
        """Log build completion"""
        self.db.table('build_logs').update({
            'completed_at': datetime.now().isoformat(),
            'records_processed': result.get('processed', 0),
            'records_succeeded': result.get('succeeded', 0),
            'records_failed': result.get('failed', 0),
            'errors': self.errors,
            'warnings': self.warnings
        }).eq('build_id', context.build_id).eq('stage', stage).execute()
        
    def _log_build_error(self, stage: str, context: ETLContext, error: str):
        """Log build error"""
        self.db.table('build_logs').update({
            'completed_at': datetime.now().isoformat(),
            'errors': [{'message': error, 'timestamp': datetime.now().isoformat()}]
        }).eq('build_id', context.build_id).eq('stage', stage).execute()