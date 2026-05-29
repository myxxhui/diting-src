from apps.exit_engine.protocols.thesis_invalid import ThesisInvalidProtocol
p = ThesisInvalidProtocol()
assert p.priority == 1, "priority 须为 1"
assert p.buffer_days == 0, "buffer_days 须为 0"
print("✅ SP3 ThesisInvalidProtocol 前置检查通过")
