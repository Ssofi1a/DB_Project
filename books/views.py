from django.contrib.auth.models import User

from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token

from .models import Section, Book
from .serializers import (
    SectionSerializer, UserSerializer,
    SectionEditSerializer, BookCreateSerializer,
    BookDetailSerializer,
)
from .custom_permissions import (
    IsAuthorPermission, IsAuthorOrCollaboratorPermission
)
from .custom_paginations import StandardResultsSetPagination


class RegisterView(APIView):
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BookCreateView(generics.ListCreateAPIView):
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request.method == "POST":
            return BookCreateSerializer
        return BookDetailSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAuthenticated()]
        return []

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def get_queryset(self):
        queryset = Book.objects.all()
        sort = self.request.query_params.get("sort_by", "-created_at")
        sorting_fields = sort.split(",")
        valid_sorting_fields = {
            "created_at", "-created_at", "title", "-title", 
            "id", "-id", "another_field", "-another_field"
        }
        sorting_fields = [field for field in sorting_fields if field in valid_sorting_fields]
        if not sorting_fields:
            sorting_fields = ["-created_at"]
        author = self.request.query_params.get("author")
        if author:
            queryset = queryset.filter(author=author)
        return queryset.order_by(*sorting_fields)


class SectionCreateView(generics.CreateAPIView):
    serializer_class = SectionSerializer
    permission_classes = [IsAuthorPermission]

    def perform_create(self, serializer):
        book = Book.objects.get(id=self.request.data["book_id"])

        if self.request.user != book.author:
            raise PermissionDenied(
                "You don't have permission to add sections to this book.")

        parent_section_id = self.request.data.get("parent_section_id", None)
        parent_section = None
        if parent_section_id:
            try:
                parent_section = Section.objects.get(id=parent_section_id)
            except Section.DoesNotExist:
                raise serializers.ValidationError(
                    "The specified parent section does not exist.")

            if parent_section.book != book:
                raise serializers.ValidationError(
                    "The parent section doesn't belong to the specified book.")

        serializer.save(
            title=self.request.data["title"], book=book, parent=parent_section)


class SectionEditView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SectionEditSerializer
    permission_classes = [IsAuthorOrCollaboratorPermission]

    def get_queryset(self):
        return Section.objects.filter(id=self.kwargs["pk"])

    def perform_update(self, serializer):
        section = self.get_object()

        if (
            self.request.user != section.book.author and
            self.request.user not in section.book.collaborators.all()
        ):
            raise PermissionDenied(
                "You don't have permission to edit this section.")

        new_title = serializer.validated_data.get("new_title")
        if new_title:
            section.title = new_title
            section.save()

    def destroy(self, request, *args, **kwargs):
        section = self.get_object()
        if request.user != section.book.author:
            raise PermissionDenied(
                "Only the author can delete this section.")
        return super().destroy(request, *args, **kwargs)


class CustomLoginView(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        response = super(CustomLoginView, self).post(request, *args, **kwargs)
        token = Token.objects.get(key=response.data["token"])
        return Response({
            "token": token.key,
            "id": token.user_id,
            "username": token.user.username
        })


class ManageCollaboratorView(APIView):
    permission_classes = [IsAuthorPermission]

    def post(self, request):
        username = request.data.get("username")
        book_id = request.data.get("book_id")
        book = Book.objects.get(id=book_id)
        if self.request.user != book.author:
            raise PermissionDenied(
                "Permission denied: You can't add collaborator to this book"
            )
        try:
            user = User.objects.get(username=username)
            book.collaborators.add(user)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response({
            "message": f"{username} is now a collaborator."
        },
            status=status.HTTP_200_OK)

    def delete(self, request):
        username = request.data.get("username")
        book_id = request.data.get("book_id")
        book = Book.objects.get(id=book_id)
        if self.request.user != book.author:
            raise PermissionDenied(
                "Permission denied: You can't delete collaborator of this book"
            )
        try:
            user = User.objects.get(username=username)
            book.collaborators.remove(user)

        except User.DoesNotExist:
            return Response({
                "error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            "message": f"{username} is no longer a collaborator."},
            status=status.HTTP_200_OK
        )
