from typing import List
import re

def split_code_into_blocks(content: str) -> List[str]:
    """코드를 간단히 블록으로 분할"""
    # 기본 정규화
    content = content.replace('\\n', '\n').strip()
    
    # 빈 줄로 분할
    blocks = []
    current_block = []
    
    for line in content.split('\n'):
        if line.strip():
            current_block.append(line)
        else:
            if current_block:
                blocks.append('\n'.join(current_block))
                current_block = []
    
    # 마지막 블록 추가
    if current_block:
        blocks.append('\n'.join(current_block))
    
    # 너무 긴 블록은 분할 (10줄 이상)
    final_blocks = []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) > 10:
            # 5줄씩 분할
            for i in range(0, len(lines), 5):
                chunk = '\n'.join(lines[i:i+5])
                if chunk.strip():
                    final_blocks.append(chunk)
        else:
            final_blocks.append(block)
    
    return [block for block in final_blocks if block.strip()]