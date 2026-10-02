import React from 'react';
import TaskListView from '../components/tasks/TaskListView';

const AllTasks = () => (
  <TaskListView
    scope="all"
    heading="All Tasks"
    subheading="Organization-wide task list"
    emptyMessage="No tasks found."
    splitByRecurrence
  />
);

export default AllTasks;
