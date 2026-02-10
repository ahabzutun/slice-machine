#!/usr/bin/env python3
"""
CDP Thread Processor
====================
Integrates SoundThread/CDP processing into the slice-machine workflow.

Usage:
    from cdp_processor import CDPProcessor

    processor = CDPProcessor(cdp_path="/Users/maxe/cdpr8/_cdp/_cdprogs")
    processor.process_file("input.wav", "output.wav", "my_thread.thd")
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional


class CDPProcessor:
    """Process audio files through SoundThread .thd processing chains."""

    def __init__(self, cdp_path: str = "/Users/maxe/cdpr8/_cdp/_cdprogs"):
        """
        Initialize CDP processor.

        Args:
            cdp_path: Path to CDP programs directory
        """
        self.cdp_path = Path(cdp_path)

        if not self.cdp_path.exists():
            raise ValueError(f"CDP path not found: {cdp_path}")

    def load_thread(self, thread_path: str) -> List[Dict]:
        """
        Load and parse a .thd file.

        Args:
            thread_path: Path to .thd file

        Returns:
            List of processing commands
        """
        with open(thread_path) as f:
            data = json.load(f)

        return self._parse_thread_data(data)

    def _parse_thread_data(self, data: Dict) -> List[Dict]:
        """Parse thread JSON data into processing chain."""
        nodes = {node['id']: node for node in data['nodes']}

        # Find input node and follow connections
        chain = []
        current_id = self._find_input_node(nodes)

        while current_id is not None:
            node = nodes[current_id]

            # Skip input/output nodes
            if node['command'] not in ['inputfile', 'outputfile']:
                cmd_info = self._build_command(node)
                chain.append(cmd_info)

            current_id = self._find_next_node(current_id, data['connections'])

        return chain

    def _find_input_node(self, nodes: Dict) -> Optional[int]:
        """Find the input file node ID."""
        for node_id, node in nodes.items():
            if node['command'] == 'inputfile':
                return node_id
        return None

    def _find_next_node(self, from_id: int, connections: List[Dict]) -> Optional[int]:
        """Find next node in processing chain."""
        for conn in connections:
            if conn['from_node_id'] == from_id:
                return conn['to_node_id']
        return None

    def _build_command(self, node: Dict) -> Dict:
        """Convert SoundThread node to CDP command info."""
        command = node['command']
        params = []

        # Extract slider values
        for key, slider in node.get('slider_values', {}).items():
            value = slider['value']
            flag = slider['meta'].get('flag', '')

            if flag:
                params.append(f"{flag}{value}")
            else:
                params.append(str(value))

        # Parse command name
        parts = command.split('_')
        program = parts[0]  # e.g., 'modify', 'focus', 'pvoc'

        if len(parts) > 1 and parts[1] not in ['anal', 'synth']:
            process = parts[1]  # e.g., 'brassage', 'radical'
        else:
            process = parts[1] if len(parts) > 1 else None

        mode = parts[-1] if len(parts) > 2 and parts[-1].isdigit() else None

        return {
            'program': program,
            'process': process,
            'mode': mode,
            'params': params,
            'original_command': command
        }

    def process_file(
        self,
        input_file: str,
        output_file: str,
        thread_path: str,
        verbose: bool = True
    ) -> None:
        """
        Process audio file through a thread.

        Args:
            input_file: Input audio file path
            output_file: Output audio file path
            thread_path: Path to .thd file
            verbose: Print progress information
        """
        chain = self.load_thread(thread_path)

        if verbose:
            print(f"\nProcessing: {Path(input_file).name}")
            print(f"Thread: {Path(thread_path).name}")
            print(f"Chain: {len(chain)} steps\n")

        with tempfile.TemporaryDirectory() as tmpdir:
            current_file = input_file

            for i, cmd in enumerate(chain):
                # Determine output path
                if i == len(chain) - 1:
                    next_file = output_file
                else:
                    # Generate temp file with appropriate extension
                    is_spectral = self._is_spectral_output(cmd)
                    ext = '.ana' if is_spectral else '.wav'
                    next_file = str(Path(tmpdir) / f"step_{i:02d}{ext}")

                # Execute command
                self._execute_command(cmd, current_file, next_file, verbose)
                current_file = next_file

    def _is_spectral_output(self, cmd: Dict) -> bool:
        """Check if command outputs spectral data."""
        return (cmd['program'] == 'pvoc' and cmd['process'] == 'anal')

    def _execute_command(
        self,
        cmd: Dict,
        input_file: str,
        output_file: str,
        verbose: bool
    ) -> None:
        """Execute a single CDP command."""
        # Build command line
        exe = self.cdp_path / cmd['program']
        args = []

        # Add process and mode if present
        if cmd['process']:
            args.append(cmd['process'])
        if cmd['mode']:
            args.append(cmd['mode'])

        # Add input/output files
        args.extend([input_file, output_file])

        # Add parameters
        args.extend(cmd['params'])

        # Full command
        full_cmd = [str(exe)] + args

        if verbose:
            cmd_str = ' '.join([exe.name] + args)
            print(f"  → {cmd_str}")

        # Execute
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            raise RuntimeError(f"CDP command failed: {error_msg}\n  Command: {' '.join(full_cmd)}")

        if verbose and result.stdout:
            # Show CDP output (indented)
            for line in result.stdout.strip().split('\n'):
                print(f"    {line}")


def integrate_with_slicer(
    slices: List[str],
    thread_path: str,
    output_dir: str,
    cdp_path: str = "/Users/maxe/cdpr8/_cdp/_cdprogs"
) -> List[str]:
    """
    Process a batch of audio slices through a CDP thread.

    Args:
        slices: List of input slice file paths
        thread_path: Path to .thd processing thread
        output_dir: Directory for processed output
        cdp_path: Path to CDP programs

    Returns:
        List of processed file paths
    """
    processor = CDPProcessor(cdp_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    processed = []

    print(f"\n{'='*60}")
    print(f"CDP BATCH PROCESSING: {len(slices)} slices")
    print(f"{'='*60}\n")

    for i, slice_path in enumerate(slices, 1):
        slice_name = Path(slice_path).stem
        output_path = output_dir / f"{slice_name}_cdp.wav"

        print(f"[{i}/{len(slices)}] {slice_name}")

        try:
            processor.process_file(
                slice_path,
                str(output_path),
                thread_path,
                verbose=False  # Less verbose for batch
            )
            processed.append(str(output_path))
            print("  ✓ Complete\n")

        except Exception as e:
            print(f"  ✗ Error: {e}\n")
            continue

    print(f"{'='*60}")
    print(f"Processed: {len(processed)}/{len(slices)} slices")
    print(f"{'='*60}\n")

    return processed


# Example usage
if __name__ == "__main__":
    # Display thread info
    processor = CDPProcessor()

    thread_data = {
        "connections": [
            {"from_node_id": 7, "to_node_id": 6},
            {"from_node_id": 6, "to_node_id": 1},
            {"from_node_id": 1, "to_node_id": 3},
            {"from_node_id": 3, "to_node_id": 2},
            {"from_node_id": 2, "to_node_id": 4},
            {"from_node_id": 4, "to_node_id": 5}
        ],
        "nodes": [
            {"id": 7, "command": "inputfile"},
            {
                "id": 6,
                "command": "modify_radical_5",
                "slider_values": {
                    "ModulatorFrequency": {
                        "value": 5.61,
                        "meta": {"flag": ""}
                    }
                }
            },
            {
                "id": 1,
                "command": "modify_brassage_4",
                "slider_values": {
                    "Grainsize": {"value": 500.0, "meta": {"flag": ""}},
                    "Range": {"value": 1.0, "meta": {"flag": "-r"}}
                }
            },
            {"id": 3, "command": "pvoc_anal_1", "slider_values": {}},
            {
                "id": 2,
                "command": "focus_step",
                "slider_values": {
                    "ClockSpeed": {"value": 0.14, "meta": {"flag": ""}}
                }
            },
            {"id": 4, "command": "pvoc_synth", "slider_values": {}},
            {"id": 5, "command": "outputfile"}
        ]
    }

    chain = processor._parse_thread_data(thread_data)

    print("Stepped Resynthesis Chain:")
    for i, cmd in enumerate(chain, 1):
        print(f"{i}. {cmd['program']}", end="")
        if cmd['process']:
            print(f" {cmd['process']}", end="")
        if cmd['mode']:
            print(f" (mode {cmd['mode']})", end="")
        if cmd['params']:
            print(f" [{', '.join(cmd['params'])}]", end="")
        print()
