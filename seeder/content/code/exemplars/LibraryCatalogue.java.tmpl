package example.library;

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

/** A lending library: books, members, loans and fines for late returns. */
public class LibraryCatalogue {

    public record Book(String isbn, String title, String author, int copies) {}

    public record Loan(String isbn, String memberId, LocalDate borrowedOn, LocalDate dueOn) {}

    private static final int LOAN_DAYS = 21;
    private static final int MAX_LOANS_PER_MEMBER = 5;
    private static final double FINE_PER_DAY = 0.20;

    private final Map<String, Book> books = new HashMap<>();
    private final List<Loan> loans = new ArrayList<>();

    public void addBook(Book book) {
        books.merge(book.isbn(), book, (existing, added) ->
                new Book(existing.isbn(), existing.title(), existing.author(),
                        existing.copies() + added.copies()));
    }

    public Optional<Book> find(String isbn) {
        return Optional.ofNullable(books.get(isbn));
    }

    public List<Book> searchByAuthor(String author) {
        String needle = author.toLowerCase();
        return books.values().stream()
                .filter(book -> book.author().toLowerCase().contains(needle))
                .sorted((a, b) -> a.title().compareToIgnoreCase(b.title()))
                .collect(Collectors.toList());
    }

    public int availableCopies(String isbn) {
        long onLoan = loans.stream().filter(loan -> loan.isbn().equals(isbn)).count();
        return find(isbn).map(book -> book.copies() - (int) onLoan).orElse(0);
    }

    public Loan borrow(String isbn, String memberId, LocalDate today) {
        if (availableCopies(isbn) <= 0) {
            throw new IllegalStateException("No copies available for " + isbn);
        }
        long held = loans.stream().filter(loan -> loan.memberId().equals(memberId)).count();
        if (held >= MAX_LOANS_PER_MEMBER) {
            throw new IllegalStateException("Member " + memberId + " has reached the loan limit");
        }
        Loan loan = new Loan(isbn, memberId, today, today.plusDays(LOAN_DAYS));
        loans.add(loan);
        return loan;
    }

    /** Returns the fine due, which is zero when the book comes back on time. */
    public double giveBack(String isbn, String memberId, LocalDate today) {
        Loan loan = loans.stream()
                .filter(item -> item.isbn().equals(isbn) && item.memberId().equals(memberId))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("No such loan"));
        loans.remove(loan);
        long daysLate = ChronoUnit.DAYS.between(loan.dueOn(), today);
        return daysLate > 0 ? Math.round(daysLate * FINE_PER_DAY * 100) / 100.0 : 0.0;
    }

    public List<Loan> overdue(LocalDate today) {
        return loans.stream()
                .filter(loan -> loan.dueOn().isBefore(today))
                .sorted((a, b) -> a.dueOn().compareTo(b.dueOn()))
                .collect(Collectors.toUnmodifiableList());
    }

    public Map<String, Long> loansPerMember() {
        return Collections.unmodifiableMap(
                loans.stream().collect(Collectors.groupingBy(Loan::memberId, Collectors.counting())));
    }
}
