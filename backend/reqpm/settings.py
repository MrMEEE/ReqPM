"""
Django settings for ReqPM project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Application definition
INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'django_filters',
    'corsheaders',
    'drf_spectacular',
    'django_celery_beat',
    'django_celery_results',
    'guardian',
    
    # ReqPM apps
    'backend.apps.core',
    'backend.apps.users',
    'backend.apps.projects',
    'backend.apps.packages',
    'backend.apps.builds',
    'backend.apps.repositories',
    'backend.apps.tasks',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.reqpm.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'backend' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.reqpm.wsgi.application'

# Database configuration
DB_ENGINE = os.getenv('DB_ENGINE', 'sqlite')

if DB_ENGINE == 'mysql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv('DB_NAME', 'reqpm'),
            'USER': os.getenv('DB_USER', 'reqpm'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'reqpm'),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '3306'),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Custom user model
AUTH_USER_MODEL = 'users.User'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'backend' / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# JWT Settings
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# Spectacular settings (API documentation)
SPECTACULAR_SETTINGS = {
    'TITLE': 'ReqPM API',
    'DESCRIPTION': 'Python Requirements to RPM Package Manager',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# CORS settings
CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS', 
    'http://localhost:3000,http://127.0.0.1:3000'
).split(',')

# Cache Configuration (required for django-celery-results)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://localhost:6379/2',
    }
}

# Celery Configuration
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'  # Store results in Django database
CELERY_CACHE_BACKEND = 'django-cache'  # Use Django cache for additional caching
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_IGNORE_RESULT = False  # Store all task results
CELERY_TASK_STORE_ERRORS_EVEN_IF_IGNORED = True  # Store errors even if task ignores results
CELERY_TASK_TIME_LIMIT = 3600  # 1 hour
CELERY_TASK_SOFT_TIME_LIMIT = 3300  # 55 minutes
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000
CELERY_RESULT_EXTENDED = True  # Store task arguments and more details

# Django Guardian settings
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'guardian.backends.ObjectPermissionBackend',
)

# ReqPM specific settings
REQPM = {
    # Build settings
    'MOCK_CONFIG_DIR': os.getenv('MOCK_CONFIG_DIR', '/etc/mock'),
    'BUILD_DIR': os.getenv('BUILD_DIR', str(BASE_DIR / 'build_artifacts')),
    'BUILD_ARTIFACTS_DIR': os.getenv('BUILD_ARTIFACTS_DIR', str(BASE_DIR / 'build_artifacts')),
    'MOCK_CACHE_DIR': os.getenv('MOCK_CACHE_DIR', str(BASE_DIR / 'mock_cache')),
    'REPOSITORY_DIR': os.getenv('REPOSITORY_DIR', str(BASE_DIR / 'repositories')),
    'GIT_CACHE_DIR': os.getenv('GIT_CACHE_DIR', str(BASE_DIR / 'git_cache')),
    
    # Build concurrency
    'MAX_CONCURRENT_BUILDS': int(os.getenv('MAX_CONCURRENT_BUILDS', '4')),
    
    # Git settings
    'GIT_DEFAULT_BRANCH': os.getenv('GIT_DEFAULT_BRANCH', 'main'),
    'GIT_TIMEOUT': int(os.getenv('GIT_TIMEOUT', '300')),
    
    # Supported RHEL versions (default)
    'DEFAULT_RHEL_VERSIONS': ['8', '9'],
    
    # Build plugins
    'BUILD_PLUGINS': {
        'mock': 'backend.plugins.builders.mock.MockBuilder',
    },
    
    # Repository plugins
    'REPOSITORY_PLUGINS': {
        'createrepo_c': 'backend.plugins.repositories.createrepo.CreateRepoManager',
    },
}

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'reqpm.log',
            'maxBytes': 1024 * 1024 * 15,  # 15MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': os.getenv('LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': os.getenv('LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'celery': {
            'handlers': ['console', 'file'],
            'level': os.getenv('LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'reqpm': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}

# Create required directories (only for writable paths)
for dir_key in ['BUILD_ARTIFACTS_DIR', 'MOCK_CACHE_DIR', 'REPOSITORY_DIR', 'GIT_CACHE_DIR']:
    dir_path = Path(REQPM[dir_key])
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Skip if we don't have permission (production directories)
        pass

# Create logs directory
try:
    (BASE_DIR / 'logs').mkdir(exist_ok=True)
except PermissionError:
    pass
