"""
backend/results/results_writer.py
=================================
Writes final execution results to JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from backend.utils.models import AgentState
from config.settings import settings

class ResultsWriter:
    def __init__(self, state: AgentState):
        self.state = state

    def write(self) -> Path:
        """Writes state.results to a JSON file in results_dir."""
        # Ensure directory exists
        run_dir = settings.results_dir_abs / self.state.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = run_dir / "results.json"
        
        # Serialize Pydantic model
        data = self.state.model_dump(mode='json')
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        return output_path
