#!/bin/bash

# MCP SSE Server 관리 스크립트
# 사용법: ./mcp_server.sh {start|stop|restart|status}

# 설정 변수
SCRIPT_NAME="mcp_sse_server.py"
SCRIPT_DIR="."     # 스크립트가 있는 디렉토리 경로
SCRIPT_PATH="$SCRIPT_DIR/mcp_sse_server.py"     # 실제 경로로 수정하세요
VENV_PATH="$SCRIPT_DIR/.venv"                   # 가상환경 경로
PID_FILE="/tmp/mcp_server.pid"
LOG_FILE="/tmp/mcp_server.log"

# 함수 정의
check_venv() {
    if [ ! -d "$VENV_PATH" ]; then
        echo "가상환경이 존재하지 않습니다: $VENV_PATH"
        echo "다음 명령어로 가상환경을 생성하세요:"
        echo "cd $SCRIPT_DIR && python3 -m venv .venv"
        return 1
    fi
    
    if [ ! -f "$VENV_PATH/bin/activate" ]; then
        echo "가상환경 활성화 스크립트가 존재하지 않습니다: $VENV_PATH/bin/activate"
        return 1
    fi
    
    return 0
}

start_server() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "MCP SSE Server가 이미 실행 중입니다. (PID: $(cat $PID_FILE))"
        return 1
    fi
    
    # 가상환경 확인
    if ! check_venv; then
        return 1
    fi
    
    # 스크립트 파일 존재 확인
    if [ ! -f "$SCRIPT_PATH" ]; then
        echo "스크립트 파일이 존재하지 않습니다: $SCRIPT_PATH"
        return 1
    fi
    
    echo "MCP SSE Server를 시작합니다..."
    echo "가상환경: $VENV_PATH"
    echo "스크립트: $SCRIPT_PATH"
    
    # 백그라운드에서 실행하고 PID 저장
    # 가상환경 활성화 후 스크립트 실행
    cd "$SCRIPT_DIR"
    nohup bash -c "source $VENV_PATH/bin/activate && python $SCRIPT_PATH" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    
    # 잠시 대기 후 프로세스 확인
    sleep 2
    if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "MCP SSE Server가 성공적으로 시작되었습니다. (PID: $(cat $PID_FILE))"
        echo "로그 파일: $LOG_FILE"
    else
        echo "MCP SSE Server 시작에 실패했습니다."
        echo "로그를 확인하세요: $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_server() {
    if [ ! -f "$PID_FILE" ]; then
        echo "PID 파일이 존재하지 않습니다. 서버가 실행되지 않은 것 같습니다."
        return 1
    fi
    
    PID=$(cat "$PID_FILE")
    
    if kill -0 "$PID" 2>/dev/null; then
        echo "MCP SSE Server를 중지합니다... (PID: $PID)"
        kill "$PID"
        
        # 프로세스가 완전히 종료될 때까지 대기
        for i in {1..10}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        
        # 여전히 실행 중이면 강제 종료
        if kill -0 "$PID" 2>/dev/null; then
            echo "강제 종료합니다..."
            kill -9 "$PID"
            sleep 1
        fi
        
        rm -f "$PID_FILE"
        echo "MCP SSE Server가 중지되었습니다."
    else
        echo "PID $PID 프로세스가 실행되지 않습니다."
        rm -f "$PID_FILE"
        return 1
    fi
}

restart_server() {
    echo "MCP SSE Server를 재시작합니다..."
    stop_server
    sleep 2
    start_server
}

status_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "MCP SSE Server가 실행 중입니다. (PID: $PID)"
            
            # 프로세스 정보 출력
            echo "프로세스 정보:"
            ps -p "$PID" -o pid,ppid,cmd,etime,pcpu,pmem
            
            # 로그 파일 마지막 몇 줄 출력
            if [ -f "$LOG_FILE" ]; then
                echo ""
                echo "최근 로그 (마지막 5줄):"
                tail -5 "$LOG_FILE"
            fi
        else
            echo "PID 파일은 존재하지만 프로세스가 실행되지 않습니다."
            rm -f "$PID_FILE"
        fi
    else
        echo "MCP SSE Server가 실행되지 않습니다."
    fi
}

show_logs() {
    if [ -f "$LOG_FILE" ]; then
        echo "로그 파일 내용:"
        cat "$LOG_FILE"
    else
        echo "로그 파일이 존재하지 않습니다."
    fi
}

# 메인 스크립트 로직
case "$1" in
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    restart)
        restart_server
        ;;
    status)
        status_server
        ;;
    logs)
        show_logs
        ;;
    *)
        echo "사용법: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "명령어:"
        echo "  start   - 서버를 시작합니다 (가상환경 자동 활성화)"
        echo "  stop    - 서버를 중지합니다"
        echo "  restart - 서버를 재시작합니다"
        echo "  status  - 서버 상태를 확인합니다"
        echo "  logs    - 로그를 출력합니다"
        echo ""
        echo "설정:"
        echo "  스크립트 디렉토리: $SCRIPT_DIR"
        echo "  가상환경 경로: $VENV_PATH"
        echo "  스크립트 파일: $SCRIPT_PATH"
        exit 1
        ;;
esac

exit 0