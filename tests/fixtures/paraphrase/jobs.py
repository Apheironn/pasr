"""Background job orchestration with morphologically-named steps."""


def schedule_recurring_jobs_on_a_cron_expression(registry, expr):
    registry.add(expr)
    return registry


def acknowledge_and_remove_a_processed_message(queue, message_id):
    queue.ack(message_id)
    queue.delete(message_id)
    return message_id


def throttle_the_worker_pool_under_high_load(pool, load):
    if load > 0.8:
        pool.scale_down()
    return pool.size


def serialize_the_job_payload_to_compact_json(payload):
    import json

    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def resurrect_a_job_that_died_mid_execution(store, job_id):
    job = store.get(job_id)
    job.state = "pending"
    store.put(job)
    return job
