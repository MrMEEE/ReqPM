#!/bin/bash
# ReqPM Control Script
# Manages Django server, Redis, Celery worker, and Celery beat

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# PID files
DJANGO_PID="$SCRIPT_DIR/.django.pid"
REDIS_PID="$SCRIPT_DIR/.redis.pid"
CELERY_PID="$SCRIPT_DIR/.celery.pid"
CELERY_BEAT_PID="$SCRIPT_DIR/.celery-beat.pid"
FRONTEND_PID="$SCRIPT_DIR/.frontend.pid"

# Log files
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
DJANGO_LOG="$LOG_DIR/django.log"
REDIS_LOG="$LOG_DIR/redis.log"
CELERY_LOG="$LOG_DIR/celery.log"
CELERY_BEAT_LOG="$LOG_DIR/celery-beat.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

# Virtual environment
VENV="$SCRIPT_DIR/venv"

# Frontend directory
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored messages
print_status() {
    echo -e "${BLUE}[ReqPM]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Function to check if process is running
is_running() {
    local pid_file=$1
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        else
            rm -f "$pid_file"
            return 1
        fi
    fi
    return 1
}

# Function to start Redis
start_redis() {
    if is_running "$REDIS_PID"; then
        print_warning "Redis is already running (PID: $(cat $REDIS_PID))"
        return 0
    fi
    
    print_status "Starting Redis..."
    
    # Check if Redis is installed
    if ! command -v redis-server &> /dev/null; then
        print_error "Redis is not installed. Please install redis-server"
        return 1
    fi
    
    # Start Redis in background
    redis-server --daemonize yes --pidfile "$REDIS_PID" --logfile "$REDIS_LOG"
    
    sleep 1
    if is_running "$REDIS_PID"; then
        print_success "Redis started (PID: $(cat $REDIS_PID))"
    else
        print_error "Failed to start Redis"
        return 1
    fi
}

# Function to start Django
start_django() {
    if is_running "$DJANGO_PID"; then
        print_warning "Django is already running (PID: $(cat $DJANGO_PID))"
        return 0
    fi
    
    print_status "Starting Django server with Daphne (WebSocket support)..."
    
    # Activate virtual environment and start Django with Daphne
    source "$VENV/bin/activate"
    
    nohup daphne -b 0.0.0.0 -p 8000 backend.reqpm.asgi:application > "$DJANGO_LOG" 2>&1 &
    echo $! > "$DJANGO_PID"
    
    sleep 2
    if is_running "$DJANGO_PID"; then
        print_success "Django started with Daphne (PID: $(cat $DJANGO_PID)) - http://localhost:8000"
    else
        print_error "Failed to start Django"
        return 1
    fi
}

# Function to start Celery worker
start_celery() {
    if is_running "$CELERY_PID"; then
        print_warning "Celery worker is already running (PID: $(cat $CELERY_PID))"
        return 0
    fi
    
    print_status "Starting Celery worker..."
    
    source "$VENV/bin/activate"
    
    nohup celery -A backend.reqpm worker -l info --pidfile="$CELERY_PID" > "$CELERY_LOG" 2>&1 &
    
    sleep 2
    if is_running "$CELERY_PID"; then
        print_success "Celery worker started (PID: $(cat $CELERY_PID))"
    else
        print_error "Failed to start Celery worker"
        return 1
    fi
}

# Function to start Celery beat
start_celery_beat() {
    if is_running "$CELERY_BEAT_PID"; then
        print_warning "Celery beat is already running (PID: $(cat $CELERY_BEAT_PID))"
        return 0
    fi
    
    print_status "Starting Celery beat..."
    
    source "$VENV/bin/activate"
    
    nohup celery -A backend.reqpm beat -l info --pidfile="$CELERY_BEAT_PID" > "$CELERY_BEAT_LOG" 2>&1 &
    
    sleep 2
    if is_running "$CELERY_BEAT_PID"; then
        print_success "Celery beat started (PID: $(cat $CELERY_BEAT_PID))"
    else
        print_error "Failed to start Celery beat"
        return 1
    fi
}

# Function to start Frontend
start_frontend() {
    if is_running "$FRONTEND_PID"; then
        print_warning "Frontend is already running (PID: $(cat $FRONTEND_PID))"
        return 0
    fi
    
    print_status "Starting Frontend (Vite dev server)..."
    
    # Check if frontend directory exists
    if [ ! -d "$FRONTEND_DIR" ]; then
        print_error "Frontend directory not found: $FRONTEND_DIR"
        return 1
    fi
    
    # Check if node_modules exists
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        print_warning "node_modules not found. Running npm install..."
        cd "$FRONTEND_DIR"
        npm install
        cd "$SCRIPT_DIR"
    fi
    
    # Start Vite dev server
    cd "$FRONTEND_DIR"
    nohup npm run dev > "$FRONTEND_LOG" 2>&1 &
    local pid=$!
    echo $pid > "$FRONTEND_PID"
    cd "$SCRIPT_DIR"
    
    sleep 3
    if is_running "$FRONTEND_PID"; then
        print_success "Frontend started (PID: $(cat $FRONTEND_PID)) - http://localhost:5173"
    else
        print_error "Failed to start Frontend"
        return 1
    fi
}

# Function to stop a service
stop_service() {
    local service_name=$1
    local pid_file=$2
    
    if ! is_running "$pid_file"; then
        print_warning "$service_name is not running"
        return 0
    fi
    
    local pid=$(cat "$pid_file")
    print_status "Stopping $service_name (PID: $pid)..."
    
    kill "$pid" 2>/dev/null || true
    
    # Wait for process to stop (max 10 seconds)
    local count=0
    while is_running "$pid_file" && [ $count -lt 10 ]; do
        sleep 1
        count=$((count + 1))
    done
    
    if is_running "$pid_file"; then
        print_warning "Force killing $service_name..."
        kill -9 "$pid" 2>/dev/null || true
        rm -f "$pid_file"
    fi
    
    print_success "$service_name stopped"
}

# Function to stop Redis
stop_redis() {
    stop_service "Redis" "$REDIS_PID"
}

# Function to stop Django
stop_django() {
    stop_service "Django" "$DJANGO_PID"
}

# Function to stop Celery worker
stop_celery() {
    stop_service "Celery worker" "$CELERY_PID"
}

# Function to stop Celery beat
stop_beat() {
    stop_service "Celery beat" "$CELERY_BEAT_PID"
}

# Function to stop Frontend
stop_frontend() {
    stop_service "Frontend" "$FRONTEND_PID"
}

# Function to check status
status() {
    echo ""
    echo "=== ReqPM Status ==="
    echo ""
    
    if is_running "$REDIS_PID"; then
        print_success "Redis:         Running (PID: $(cat $REDIS_PID))"
    else
        print_error "Redis:         Stopped"
    fi
    
    if is_running "$DJANGO_PID"; then
        print_success "Django:        Running (PID: $(cat $DJANGO_PID)) - http://localhost:8000"
    else
        print_error "Django:        Stopped"
    fi
    
    if is_running "$CELERY_PID"; then
        print_success "Celery Worker: Running (PID: $(cat $CELERY_PID))"
    else
        print_error "Celery Worker: Stopped"
    fi
    
    if is_running "$CELERY_BEAT_PID"; then
        print_success "Celery Beat:   Running (PID: $(cat $CELERY_BEAT_PID))"
    else
        print_error "Celery Beat:   Stopped"
    fi
    
    if is_running "$FRONTEND_PID"; then
        print_success "Frontend:      Running (PID: $(cat $FRONTEND_PID)) - http://localhost:5173"
    else
        print_error "Frontend:      Stopped"
    fi
    
    echo ""
}

# Function to start all services
start_all() {
    echo ""
    echo "=== Starting ReqPM Services ==="
    echo ""
    
    start_redis
    start_django
    start_celery
    start_celery_beat
    start_frontend
    
    echo ""
    status
}

# Function to stop all services
stop_all() {
    echo ""
    echo "=== Stopping ReqPM Services ==="
    echo ""
    
    stop_frontend
    stop_beat
    stop_celery
    stop_django
    stop_redis
    
    echo ""
    print_success "All services stopped"
    echo ""
}

# Function to restart all services
restart_all() {
    echo ""
    echo "=== Restarting ReqPM Services ==="
    echo ""
    
    stop_all
    sleep 2
    start_all
}

# Function to restart individual service
restart_service() {
    local service=$1
    
    echo ""
    echo "=== Restarting $service ==="
    echo ""
    
    case "$service" in
        django)
            stop_django
            sleep 1
            start_django
            ;;
        redis)
            stop_redis
            sleep 1
            start_redis
            ;;
        celery)
            stop_celery
            sleep 1
            start_celery
            ;;
        beat)
            stop_beat
            sleep 1
            start_celery_beat
            ;;
        frontend)
            stop_frontend
            sleep 1
            start_frontend
            ;;
        all)
            restart_all
            ;;
        *)
            print_error "Unknown service: $service"
            echo "Available: django, redis, celery, beat, frontend, all"
            exit 1
            ;;
    esac
}

# Function to show logs
logs() {
    local service=$1
    
    case "$service" in
        django)
            tail -f "$DJANGO_LOG"
            ;;
        redis)
            tail -f "$REDIS_LOG"
            ;;
        celery)
            tail -f "$CELERY_LOG"
            ;;
        beat)
            tail -f "$CELERY_BEAT_LOG"
            ;;
        frontend)
            tail -f "$FRONTEND_LOG"
            ;;
        all)
            tail -f "$DJANGO_LOG" "$REDIS_LOG" "$CELERY_LOG" "$CELERY_BEAT_LOG" "$FRONTEND_LOG"
            ;;
        *)
            print_error "Unknown service: $service"
            echo "Available: django, redis, celery, beat, frontend, all"
            exit 1
            ;;
    esac
}

# Main script
case "${1:-}" in
    start)
        if [ -n "${2:-}" ]; then
            case "$2" in
                django) start_django ;;
                redis) start_redis ;;
                celery) start_celery ;;
                beat) start_celery_beat ;;
                frontend) start_frontend ;;
                all) start_all ;;
                *)
                    print_error "Unknown service: $2"
                    echo "Available: django, redis, celery, beat, frontend, all"
                    exit 1
                    ;;
            esac
        else
            start_all
        fi
        ;;
    stop)
        if [ -n "${2:-}" ]; then
            case "$2" in
                django) stop_django ;;
                redis) stop_redis ;;
                celery) stop_celery ;;
                beat) stop_beat ;;
                frontend) stop_frontend ;;
                all) stop_all ;;
                *)
                    print_error "Unknown service: $2"
                    echo "Available: django, redis, celery, beat, frontend, all"
                    exit 1
                    ;;
            esac
        else
            stop_all
        fi
        ;;
    restart)
        if [ -n "${2:-}" ]; then
            restart_service "$2"
        else
            restart_all
        fi
        ;;
    status)
        status
        ;;
    logs)
        if [ -z "${2:-}" ]; then
            print_error "Please specify service: django, redis, celery, beat, frontend, or all"
            exit 1
        fi
        logs "$2"
        ;;
    start-redis)
        start_redis
        ;;
    stop-redis)
        stop_redis
        ;;
    start-django)
        start_django
        ;;
    stop-django)
        stop_django
        ;;
    start-celery)
        start_celery
        ;;
    stop-celery)
        stop_celery
        ;;
    start-beat)
        start_celery_beat
        ;;
    stop-beat)
        stop_beat
        ;;
    start-frontend)
        start_frontend
        ;;
    stop-frontend)
        stop_frontend
        ;;
    *)
        echo "ReqPM Control Script"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs} [service]"
        echo ""
        echo "Commands:"
        echo "  start [service]   - Start all services or specific service"
        echo "  stop [service]    - Stop all services or specific service"
        echo "  restart [service] - Restart all services or specific service"
        echo "  status            - Show status of all services"
        echo "  logs <service>    - Tail logs (django|redis|celery|beat|frontend|all)"
        echo ""
        echo "Services: django, redis, celery, beat, frontend, all"
        echo ""
        echo "Individual service control (legacy):"
        echo "  start-redis, stop-redis"
        echo "  start-django, stop-django"
        echo "  start-celery, stop-celery"
        echo "  start-beat, stop-beat"
        echo "  start-frontend, stop-frontend"
        echo ""
        exit 1
        ;;
esac
