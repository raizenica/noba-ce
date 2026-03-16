#!/usr/bin/env bats

load '../libexec/noba/lib/noba-lib.sh'
load '../libexec/noba/noba-web/functions.sh'

@test "find_free_port returns a number" {
    run find_free_port 8000 8010
    [ "$status" -eq 0 ]
    [[ "$output" =~ ^[0-9]+$ ]]
}

@test "show_version returns something" {
    NOBA_ROOT="$BATS_TEST_DIRNAME/.."
    run show_version
    [ "$status" -eq 0 ]
    [ -n "$output" ]
}
