-- atomic_release.lua
-- Atomically release `amount` lots from an in-flight reservation counter.
-- Saturates at zero — never goes negative.
--
-- KEYS[1] = "account:{id}:reserved_lots"
-- ARGV[1] = amount       (lots being released)
-- ARGV[2] = ttl_seconds  (TTL refresh on the surviving counter; 0 = none)
--
-- Returns: { new_reserved_str, previous_reserved_str }
--
-- Story 10.4 — companion to atomic_reserve.lua. Called after a ZMQ send
-- result (filled, rejected, or timeout) so the reservation doesn't pile
-- up indefinitely. The TTL refresh keeps the counter alive across long
-- sessions of small reserve/release cycles, mirroring atomic_reserve.

local key = KEYS[1]
local amount = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

if amount == nil then
  return redis.error_reply("atomic_release: amount must be a number")
end
if amount < 0 then
  return redis.error_reply("atomic_release: amount must be non-negative")
end

local raw = redis.call('GET', key)
local current = 0
if raw ~= false then
  current = tonumber(raw) or 0
end

local new = current - amount
if new < 0 then
  new = 0
end

if new == 0 then
  redis.call('DEL', key)
else
  redis.call('SET', key, tostring(new))
  if ttl ~= nil and ttl > 0 then
    redis.call('EXPIRE', key, ttl)
  end
end

return { tostring(new), tostring(current) }
