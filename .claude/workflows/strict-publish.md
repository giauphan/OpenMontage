1. **Preflight**: Verify Meta tokens and Claude CLI availability.
2. **Prepare**: Select projects due today from `config/publish_schedule.json`.
3. **Today-batch**: Validate, Claude-review, and publish today's projects.
4. **Generate**: Produce next-day videos via `run_daily_news_pipeline.sh`.
5. **Verify**: Validate generated assets.
6. **Queue-next-day**: Update `config/publish_schedule.json`.
7. **Platform-schedule**: Schedule platform-specific publishing.
8. **Final-state**: Log completion.
