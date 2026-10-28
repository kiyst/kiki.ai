# Request retry policy

Client requests may be attempted up to three times when a transient network
failure occurs. Wait two seconds before the second attempt and four seconds
before the third attempt. Authentication and validation failures must not be
retried.

If all attempts fail, return the final error and preserve its request ID for
diagnosis.

