module.exports = {
  apps: [
    {
      name: 'gold-bot',
      script: 'main.py',
      interpreter: './venv/bin/python3',
      cwd: __dirname,
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '256M',
      restart_delay: 5000,
      env: {
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      out_file: './logs/pm2-out.log',
      error_file: './logs/pm2-err.log',
      merge_logs: true,
    },
  ],
};
