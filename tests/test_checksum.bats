#!/usr/bin/env bats

setup() {
    # Create a temporary test file
    echo "test data" > testfile.txt
}

teardown() {
    # Clean up generated files
    rm -f testfile.txt testfile.txt.md5.txt
}

@test "checksum --version returns version" {
    run ../checksum.sh --version
    [ "$status" -eq 0 ]
    [[ "$output" =~ "version" ]]
}

@test "checksum generates md5 for a file" {
    run ../checksum.sh -a md5 testfile.txt
    [ "$status" -eq 0 ]
    # The script creates filename.algorithm.txt
    [ -f "testfile.txt.md5.txt" ]
    # Verify content contains the filename
    grep -q "testfile.txt" "testfile.txt.md5.txt"
}
