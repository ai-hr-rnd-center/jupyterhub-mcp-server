from typing import List

def split_code_into_blocks(content: str) -> List[str]:
    """코드를 논리적 블록으로 분할"""
    # 문자열 정규화
    if '\\n' in content:
        content = content.replace('\\n', '\n')
    
    lines = content.split('\n')
    blocks = []
    current_block = []
    
    # 빈 줄이나 주석으로 구분되는 블록 단위로 분할
    for line in lines:
        stripped_line = line.strip()
        
        # 빈 줄을 만나면 현재 블록 완료
        if not stripped_line:
            if current_block:
                blocks.append('\n'.join(current_block))
                current_block = []
        else:
            current_block.append(line)
    
    # 마지막 블록 추가
    if current_block:
        blocks.append('\n'.join(current_block))
    
    # 너무 큰 블록은 추가로 분할
    final_blocks = []
    for block in blocks:
        if len(block.split('\n')) > 20:  # 20줄 이상이면 분할
            final_blocks.extend(split_large_block(block))
        else:
            final_blocks.append(block)
    
    return final_blocks

def split_large_block(block: str) -> List[str]:
    """큰 블록을 더 작은 단위로 분할"""
    lines = block.split('\n')
    blocks = []
    current_block = []
    
    for line in lines:
        current_block.append(line)
        
        # 함수 정의나 클래스 정의 후에 분할
        if (line.strip().startswith('def ') or 
            line.strip().startswith('class ') or
            line.strip().startswith('import ') or
            line.strip().startswith('from ')) and len(current_block) > 1:
            
            if len(current_block) > 1:
                blocks.append('\n'.join(current_block[:-1]))
                current_block = [line]
        
        # 10줄마다 강제 분할
        elif len(current_block) >= 10:
            blocks.append('\n'.join(current_block))
            current_block = []
    
    if current_block:
        blocks.append('\n'.join(current_block))
    
    return blocks

def mask_non_text_outputs(outputs):
    """출력에서 non-text 데이터를 마스킹 처리"""
    masked_outputs = []
    
    for output in outputs:
        if output.get('output_type') == 'stream':
            masked_outputs.append(output.get('text', ''))
        
        elif output.get('output_type') in ('execute_result', 'display_data'):
            parts = []
            data = output.get('data', {})
            for mime, content in data.items():
                if mime == 'text/plain':
                    parts.append(content)
                else:
                    parts.append(f"[{mime} result exists]")
            masked_outputs.append("\n".join(parts))
        
        elif output.get('output_type') == 'error':
            traceback = output.get('traceback', [])
            masked_outputs.append("[Error] " + '\n'.join(traceback))
        
        else:
            masked_outputs.append("[unknown output type]")
    
    return masked_outputs

def strip_ansi_codes(text: str) -> str:
    """ANSI 컬러 코드 제거"""
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def truncate_output(text: str, max_length: int = 1000, reverse: bool = False) -> str:
    """출력 길이 제한"""
    msg = "( Truncated )"
    if len(text) > max_length:
        if reverse:
            return msg + '\n' + text[::-1][:max_length][::-1]
        else:
            return text[:max_length] + '\n' + msg
    else:
        return text

def format_error_output(error: Exception, additional_info: List[str] = None) -> dict:
    """표준화된 에러 출력 객체 생성"""
    traceback = additional_info or []
    if not traceback:
        traceback = [strip_ansi_codes(str(error))]
    
    return {
        "output_type": "error",
        "ename": type(error).__name__,
        "evalue": str(error),
        "traceback": traceback
    }

def validate_notebook_path(path: str) -> bool:
    """노트북 경로 검증"""
    if not path:
        return False
    
    # 기본적인 경로 검증
    if path.startswith('/') or '..' in path:
        return False
    
    # .ipynb 확장자 확인
    if not path.endswith('.ipynb'):
        return False
    
    return True

def validate_cell_content(content: str) -> bool:
    """셀 내용 검증"""
    if not isinstance(content, str):
        return False
    
    # 너무 긴 내용 제한 (100KB)
    if len(content) > 100 * 1024:
        return False
    
    return True

def format_response(success: bool, data: dict = None, error: str = None) -> dict:
    """표준화된 응답 형식"""
    response = {
        "success": success,
        "timestamp": __import__('time').time()
    }
    
    if success and data:
        response.update(data)
    elif not success and error:
        response["error"] = error
    
    return response