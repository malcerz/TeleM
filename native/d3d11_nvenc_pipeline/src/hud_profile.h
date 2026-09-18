#ifndef TELEM_HUD_PROFILE_H
#define TELEM_HUD_PROFILE_H

#include <string>
#include <stdint.h>

namespace TelemHudProfile {

// Diagnostic-only profiler. It is inert unless TELEM_NATIVE_HUD_PROFILE=1.
bool Enabled();
void Reset();
double NowSeconds();
void Record(const char* table, const char* item, const char* stage, double milliseconds);
void Count(const char* table, const char* item);
void Timeline(uint32_t frame, const char* event);
void Update(uint32_t frame, const char* item, const char* value);
void Dump();

} // namespace TelemHudProfile

#endif
