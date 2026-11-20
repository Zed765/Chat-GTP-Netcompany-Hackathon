<?php

declare(strict_types=1);

namespace Example\Website;

/**
 * Validates and handles the contact form of a small website.
 */
final class ContactForm
{
    private const MAX_MESSAGE_LENGTH = 2000;
    private const TOPICS = ['general', 'support', 'sales', 'press'];

    /** @var array<string, string> */
    private array $errors = [];

    /** @var array<string, string> */
    private array $values = [];

    /**
     * @param array<string, mixed> $input
     */
    public function __construct(array $input)
    {
        foreach (['name', 'email', 'topic', 'message'] as $field) {
            $this->values[$field] = trim((string) ($input[$field] ?? ''));
        }
        $this->values['newsletter'] = isset($input['newsletter']) ? '1' : '0';
    }

    public function validate(): bool
    {
        $this->errors = [];

        if ($this->values['name'] === '') {
            $this->errors['name'] = 'Please tell us your name.';
        } elseif (mb_strlen($this->values['name']) > 80) {
            $this->errors['name'] = 'The name is too long.';
        }

        if (filter_var($this->values['email'], FILTER_VALIDATE_EMAIL) === false) {
            $this->errors['email'] = 'Please enter a valid email address.';
        }

        if (!in_array($this->values['topic'], self::TOPICS, true)) {
            $this->errors['topic'] = 'Please choose a topic from the list.';
        }

        $length = mb_strlen($this->values['message']);
        if ($length < 10) {
            $this->errors['message'] = 'The message is too short.';
        } elseif ($length > self::MAX_MESSAGE_LENGTH) {
            $this->errors['message'] = sprintf(
                'The message may be at most %d characters long.',
                self::MAX_MESSAGE_LENGTH
            );
        }

        return $this->errors === [];
    }

    /** @return array<string, string> */
    public function errors(): array
    {
        return $this->errors;
    }

    public function value(string $field): string
    {
        return htmlspecialchars($this->values[$field] ?? '', ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    }

    public function wantsNewsletter(): bool
    {
        return $this->values['newsletter'] === '1';
    }

    /**
     * Appends the message to a log file, one JSON document per line.
     */
    public function store(string $path): void
    {
        if ($this->errors !== []) {
            throw new \LogicException('Cannot store a form that failed validation.');
        }

        $record = [
            'received' => gmdate('c'),
            'name' => $this->values['name'],
            'email' => $this->values['email'],
            'topic' => $this->values['topic'],
            'message' => $this->values['message'],
            'newsletter' => $this->wantsNewsletter(),
        ];
        $line = json_encode($record, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR) . PHP_EOL;

        if (file_put_contents($path, $line, FILE_APPEND | LOCK_EX) === false) {
            throw new \RuntimeException('The message could not be saved.');
        }
    }

    public function subjectLine(): string
    {
        $topic = ucfirst($this->values['topic']);
        $preview = mb_substr(preg_replace('/\s+/', ' ', $this->values['message']) ?? '', 0, 40);

        return sprintf('[%s] %s', $topic, $preview);
    }
}
