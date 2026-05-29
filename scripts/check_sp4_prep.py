from apps.exit_engine.protocols.rebalance import RebalanceProtocol
p = RebalanceProtocol()
assert p.priority == 3, "priority 须为 3"
assert p.buffer_days == 7, "buffer_days 须为 7"
print("✅ SP4 RebalanceProtocol 前置检查通过")
