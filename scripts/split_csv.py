#!/usr/bin/env python3
"""
Split a large CSV file into multiple smaller files for batch processing.

This is useful for:
- Managing large imports in chunks
- Monitoring progress
- Resuming if a chunk fails
- Avoiding system overload
"""
import argparse
import csv
from pathlib import Path
from typing import Generator
import math


def count_rows(file_path: Path) -> int:
    """Count total rows in CSV file (excluding header)"""
    with open(file_path, 'r', encoding='utf-8') as f:
        # Skip BOM if present
        first_char = f.read(1)
        if first_char != '\ufeff':
            f.seek(0)
        
        reader = csv.reader(f)
        # Skip header
        next(reader, None)
        return sum(1 for _ in reader)


def split_csv(
    input_file: Path,
    output_dir: Path,
    num_chunks: int,
    prefix: str = "chunk"
) -> list[Path]:
    """
    Split CSV file into multiple chunks.
    
    Returns list of output file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Count total rows
    print(f"Counting rows in {input_file}...")
    total_rows = count_rows(input_file)
    rows_per_chunk = math.ceil(total_rows / num_chunks)
    
    print(f"Total rows: {total_rows:,}")
    print(f"Rows per chunk: {rows_per_chunk:,}")
    print(f"Creating {num_chunks} chunks...")
    
    output_files = []
    
    with open(input_file, 'r', encoding='utf-8') as f:
        # Skip BOM if present
        first_char = f.read(1)
        if first_char != '\ufeff':
            f.seek(0)
        else:
            print("Skipped BOM in input file")
        
        reader = csv.DictReader(f)
        header = reader.fieldnames
        
        if not header:
            raise ValueError("CSV file has no header row")
        
        current_chunk = 0
        current_row = 0
        current_file = None
        current_writer = None
        
        for row in reader:
            # Start new chunk if needed
            if current_row == 0:
                if current_file:
                    current_file.close()
                
                chunk_num = current_chunk + 1
                output_file = output_dir / f"{prefix}_{chunk_num:02d}.csv"
                output_files.append(output_file)
                
                current_file = open(output_file, 'w', encoding='utf-8', newline='')
                current_writer = csv.DictWriter(current_file, fieldnames=header)
                current_writer.writeheader()
                
                print(f"  Creating chunk {chunk_num}/{num_chunks}: {output_file.name}")
            
            # Write row
            current_writer.writerow(row)
            current_row += 1
            
            # Move to next chunk if we've filled this one
            if current_row >= rows_per_chunk:
                current_chunk += 1
                current_row = 0
        
        # Close last file
        if current_file:
            current_file.close()
    
    print(f"\n✅ Successfully created {len(output_files)} chunks")
    print(f"Output directory: {output_dir}")
    
    return output_files


def main():
    parser = argparse.ArgumentParser(
        description='Split a large CSV file into multiple smaller chunks',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Split into 10 chunks
  python scripts/split_csv.py data/master/all_games_master.csv --chunks 10
  
  # Split into 20 chunks with custom prefix
  python scripts/split_csv.py data/master/all_games_master.csv --chunks 20 --prefix games_chunk
  
  # Split into chunks and output to specific directory
  python scripts/split_csv.py data/master/all_games_master.csv --chunks 10 --output data/chunks
        """
    )
    
    parser.add_argument('input_file', type=Path, help='Input CSV file to split')
    parser.add_argument('--chunks', type=int, default=10, help='Number of chunks to create (default: 10)')
    parser.add_argument('--output', type=Path, default=None, help='Output directory (default: same as input file directory/chunks)')
    parser.add_argument('--prefix', type=str, default='chunk', help='Prefix for output files (default: chunk)')
    
    args = parser.parse_args()
    
    if not args.input_file.exists():
        print(f"Error: Input file not found: {args.input_file}")
        return 1
    
    # Determine output directory
    if args.output:
        output_dir = args.output
    else:
        # Default: create 'chunks' subdirectory in same directory as input file
        output_dir = args.input_file.parent / 'chunks'
    
    try:
        output_files = split_csv(
            args.input_file,
            output_dir,
            args.chunks,
            args.prefix
        )
        
        print("\n" + "="*80)
        print("📋 Chunk Files Created:")
        print("="*80)
        for i, file_path in enumerate(output_files, 1):
            file_size = file_path.stat().st_size / (1024 * 1024)  # MB
            print(f"  {i:2d}. {file_path.name} ({file_size:.2f} MB)")
        
        print("\n" + "="*80)
        print("🚀 To import each chunk, run:")
        print("="*80)
        print("python scripts/import_games_copy.py <chunk_file> gotsport")
        print("\nOr import all chunks sequentially:")
        for i, file_path in enumerate(output_files, 1):
            rel_path = file_path.relative_to(Path.cwd())
            print(f"python scripts/import_games_copy.py {rel_path} gotsport")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())

