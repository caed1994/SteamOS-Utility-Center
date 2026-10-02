// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Drives panel_rtc.c against a PCF85063 made of its 18 registers, 00h to
// 11h, with an address that counts up after each byte and starts again at
// 00h after 11h, as the datasheet says. A test on this machine reads it.
//
// Commands on standard input, one to a line:
//
//   set <register> <value>   both in hexadecimal
//   absent                   nothing answers at 0x51
//   fail <n>                 the n-th transfer from now fails, 1 the next
//   init                     panel_rtc_init: "init <error>"
//   read                     panel_rtc_read: "time <seconds>" or "none"
//   write <seconds>          panel_rtc_write: "write <error>"
//   decode <control> <seven bytes>
//                            panel_rtc_decode: "time <seconds>" or "none"
//   encode <seconds>         panel_rtc_encode: "bytes <seven bytes>" or "none"
//   show                     the registers 00h to 0Ah
//
// Each transfer is printed as it goes: "r <first> <count>" for a read,
// "w <first> <bytes>" for a write, and "x" for one that fails. The writes
// by register come at the end.
// See tests/test_panel_rtc.py.

#include <stdio.h>
#include <string.h>

#include "driver/i2c_master.h"
#include "bsp/esp-bsp.h"
#include "panel_rtc.h"

#define REGISTERS 0x12

static uint8_t registers[REGISTERS];
static int writes[REGISTERS];
static int absent, fail_at, transfers;
static uint16_t address;

const char *esp_err_to_name(esp_err_t err)
{
    switch (err) {
    case ESP_OK: return "ESP_OK";
    case ESP_ERR_INVALID_ARG: return "ESP_ERR_INVALID_ARG";
    case ESP_ERR_INVALID_STATE: return "ESP_ERR_INVALID_STATE";
    case ESP_ERR_NOT_FOUND: return "ESP_ERR_NOT_FOUND";
    default: return "ESP_FAIL";
    }
}

i2c_master_bus_handle_t bsp_i2c_get_handle(void)
{
    return (i2c_master_bus_handle_t)registers;
}

/* false for a transfer to a device nobody added, and for the transfer
 * that the command fail chose. */
static int goes_through(void)
{
    transfers++;
    if (address != 0x51) {
        printf("x nobody\n");
        return 0;
    }
    if (fail_at && transfers == fail_at) {
        printf("x\n");
        return 0;
    }
    return 1;
}

esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t device,
                                      const uint8_t *write, size_t write_size,
                                      uint8_t *read, size_t read_size,
                                      int timeout_ms)
{
    (void)device; (void)timeout_ms;
    if (!goes_through()) return ESP_FAIL;
    if (write_size != 1 || write[0] >= REGISTERS) {
        printf("bad read\n");
        return ESP_FAIL;
    }
    printf("r %02x %zu\n", write[0], read_size);
    for (size_t i = 0; i < read_size; i++)
        read[i] = registers[(write[0] + i) % REGISTERS];
    return ESP_OK;
}

esp_err_t i2c_master_transmit(i2c_master_dev_handle_t device,
                              const uint8_t *write, size_t write_size,
                              int timeout_ms)
{
    (void)device; (void)timeout_ms;
    if (!goes_through()) return ESP_FAIL;
    if (write_size < 2 || write[0] >= REGISTERS) {
        printf("bad write\n");
        return ESP_FAIL;
    }
    printf("w %02x", write[0]);
    for (size_t i = 1; i < write_size; i++) {
        int reg = (write[0] + i - 1) % REGISTERS;
        printf(" %02x", write[i]);
        registers[reg] = write[i];
        writes[reg]++;
    }
    printf("\n");
    return ESP_OK;
}

esp_err_t i2c_master_probe(i2c_master_bus_handle_t bus, uint16_t at, int timeout_ms)
{
    (void)bus; (void)timeout_ms;
    return !absent && at == 0x51 ? ESP_OK : ESP_FAIL;
}

esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t bus,
                                    const i2c_device_config_t *config,
                                    i2c_master_dev_handle_t *device)
{
    (void)bus;
    address = config->device_address;
    *device = (i2c_master_dev_handle_t)registers;
    return ESP_OK;
}

esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t device)
{
    (void)device;
    return ESP_OK;
}

static void show_time(bool ok, time_t utc)
{
    if (ok) printf("time %lld\n", (long long)utc);
    else printf("none\n");
}

int main(void)
{
    /* The registers after a power-on, from the table of reset values: the
     * flag OS set, and 2000-01-01, a Saturday. */
    registers[0x04] = 0x80;
    registers[0x07] = 0x01;
    registers[0x08] = 0x06;
    registers[0x09] = 0x01;
    registers[0x0B] = registers[0x0C] = registers[0x0D] = registers[0x0E] = 0x80;
    registers[0x0F] = 0x80;
    registers[0x11] = 0x18;
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        unsigned reg, value, control, b[7];
        long long seconds;
        int n;
        if (sscanf(line, "set %x %x", &reg, &value) == 2) {
            registers[reg % REGISTERS] = (uint8_t)value;
        } else if (strncmp(line, "absent", 6) == 0) {
            absent = 1;
        } else if (sscanf(line, "fail %d", &n) == 1) {
            fail_at = transfers + n;
        } else if (strncmp(line, "init", 4) == 0) {
            printf("init %s\n", esp_err_to_name(panel_rtc_init()));
        } else if (strncmp(line, "read", 4) == 0) {
            time_t utc = 0;
            bool ok = panel_rtc_read(&utc);
            show_time(ok, utc);
        } else if (sscanf(line, "write %lld", &seconds) == 1) {
            printf("write %s\n", esp_err_to_name(panel_rtc_write((time_t)seconds)));
        } else if (sscanf(line, "decode %x %x %x %x %x %x %x %x", &control, &b[0], &b[1],
                          &b[2], &b[3], &b[4], &b[5], &b[6]) == 8) {
            uint8_t bytes[7];
            for (int i = 0; i < 7; i++) bytes[i] = (uint8_t)b[i];
            time_t utc = 0;
            bool ok = panel_rtc_decode((uint8_t)control, bytes, &utc);
            show_time(ok, utc);
        } else if (sscanf(line, "encode %lld", &seconds) == 1) {
            uint8_t bytes[7];
            if (panel_rtc_encode((time_t)seconds, bytes)) {
                printf("bytes");
                for (int i = 0; i < 7; i++) printf(" %02x", bytes[i]);
                printf("\n");
            } else {
                printf("none\n");
            }
        } else if (strncmp(line, "show", 4) == 0) {
            printf("registers");
            for (int i = 0; i <= 0x0A; i++) printf(" %02x", registers[i]);
            printf("\n");
        } else {
            return 2;
        }
        fflush(stdout);
    }
    printf("writes:");
    int none = 1;
    for (int i = 0; i < REGISTERS; i++) {
        if (writes[i]) {
            printf(" %02x*%d", i, writes[i]);
            none = 0;
        }
    }
    printf("%s\n", none ? " none" : "");
    return 0;
}
